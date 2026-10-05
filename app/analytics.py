"""Deterministic supervisory signals. Findings are hypotheses for human review."""
import csv
import hashlib
import io
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from .patterns import operational_profiles

ENGINE_VERSION = "1.3.0"
DEFAULT_POLICY = {
    "fast_closure_minutes": 2,
    "escalation_severities": ["critical"],
    "repeated_alert_minimum": 4,
    "repeated_note_minimum": 3,
    "coverage_stale_hours": 72,
    "acknowledgement_sla_minutes": 30,
}
SCHEMAS = {
    "alerts": {"required": ["alert_id", "asset_id", "category", "severity", "created_at"],
               "optional": ["acknowledged_at", "case_id"]},
    "cases": {"required": ["case_id", "opened_at", "status"],
              "optional": ["closed_at", "asset_id", "severity", "investigation_notes", "closure_reason", "approved_automation", "approved_exception", "remediation_reference", "investigation_required", "oversight_required", "recovery_validation_required"]},
    "escalations": {"required": ["escalation_id", "case_id", "escalated_at"], "optional": ["destination_role"]},
    "assets": {"required": ["asset_id", "asset_type", "criticality", "expected_monitoring"], "optional": ["name"]},
    "coverage": {"required": ["asset_id", "monitoring_source", "coverage_status", "last_seen_at"], "optional": []},
    "expectations": {"required": ["expectation_id", "asset_id", "category", "min_alerts", "expectation_basis"], "optional": ["approved_exception"]},
    "workflow": {"required": ["event_id", "case_id", "event_type", "performed_at"], "optional": ["actor_role", "evidence_reference", "result"]},
}
DOMAINS = ["Detection", "Investigation", "Escalation", "Response", "Security operations", "Governance", "Operational discipline", "Cyber resilience"]
DETECTORS = [
    {"id": "fast_closure", "name": "Unsupported rapid closure", "domain": "Investigation", "kind": "Execution gap",
     "description": "High or critical cases closed below the configured duration with weak notes or no closure rationale. Approved automated closures are excluded."},
    {"id": "missing_escalation", "name": "Required escalation absent", "domain": "Escalation", "kind": "Execution gap",
     "description": "Closed cases matching the entity's escalation policy have no linked escalation. Requires an escalation submission."},
    {"id": "repeated_notes", "name": "Repeated investigation narrative", "domain": "Investigation", "kind": "Execution gap",
     "description": "Identical normalised notes reused across cases on different assets. A review hypothesis: standard playbooks can be legitimate."},
    {"id": "recurring_alerts", "name": "Recurring alerts without recorded remediation", "domain": "Response", "kind": "Execution gap",
     "description": "Repeated asset/category combinations with no remediation reference in linked cases. References are not proof of effective remediation."},
    {"id": "coverage_gap", "name": "Critical monitoring coverage gap", "domain": "Detection", "kind": "Negative space",
     "description": "Critical assets explicitly requiring monitoring lack an active, sufficiently recent source. Zero alerts alone never imply a gap."},
    {"id": "unlinked_case", "name": "Referenced investigation unavailable", "domain": "Operational discipline", "kind": "Negative space",
     "description": "Alerts reference cases absent from the submitted case export. May reflect an incomplete export rather than absent investigation."},
    {"id": "closure_outlier", "name": "Unusually short investigation with weak evidence", "domain": "Investigation", "kind": "Execution gap",
     "description": "High/critical closures below Q1 minus 1.5 IQR of at least 20 non-approved closures, with weak notes or missing rationale. An explainable distribution outlier, not a verdict."},
    {"id": "sla_edge", "name": "SLA-edge acknowledgements with weak investigation", "domain": "Operational discipline", "kind": "Execution gap",
     "description": "At least 10 and half of eligible acknowledgements cluster in the last 10% of the configured SLA; linked in-period closed cases have weak investigation evidence. Batching can be legitimate; intent is not inferred."},
    {"id": "expected_category", "name": "Expected alert activity absent", "domain": "Detection", "kind": "Negative space",
     "description": "Asset/category activity falls below a submitted, justified minimum expectation. Zero alerts alone do not establish failure."},
    {"id": "workflow_gap", "name": "Required investigation workflow evidence absent", "domain": "Security operations", "kind": "Negative space",
     "description": "Closed cases explicitly requiring investigation lack a referenced investigation event before closure."},
    {"id": "oversight_gap", "name": "Required oversight evidence absent", "domain": "Governance", "kind": "Negative space",
     "description": "Closed cases explicitly requiring oversight lack a review event with reviewer role and evidence reference before closure."},
    {"id": "recovery_gap", "name": "Required recovery validation unresolved", "domain": "Cyber resilience", "kind": "Execution gap",
     "description": "Closed cases explicitly requiring recovery validation lack a successful referenced recovery test, or the latest test failed."},
    {"id": "profile_outlier", "name": "Unusual operational evidence profile", "domain": "Operational discipline", "kind": "Execution gap",
     "description": "At least two case features lie outside inclusive IQR fences in a same-severity cohort of at least 20 non-approved closed cases. Candidate novel patterns require examiner interpretation."},
]
META = {d["id"]: d for d in DETECTORS}


def timestamp(value):
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def truth(value):
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def canonical(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def validate_policy(policy):
    result = dict(DEFAULT_POLICY)
    result.update(policy or {})
    for key, lo, hi in [("fast_closure_minutes", .1, 120), ("repeated_alert_minimum", 2, 1000), ("repeated_note_minimum", 2, 1000), ("coverage_stale_hours", 1, 8760), ("acknowledgement_sla_minutes", 1, 1440)]:
        val = result[key]
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not lo <= val <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}.")
        if key.startswith("repeated_") and int(val) != val:
            raise ValueError(f"{key} must be a whole number.")
    sev = result["escalation_severities"]
    if not isinstance(sev, list) or any(s not in ["critical", "high", "medium", "low", "info"] for s in sev):
        raise ValueError("Invalid escalation severities.")
    return {k: result[k] for k in DEFAULT_POLICY}


def parse_file(kind, file):
    if kind not in SCHEMAS:
        raise ValueError("Unknown file type.")
    if not isinstance(file, dict):
        raise ValueError("Each file must be an object with a filename and text content.")
    content = file.get("content", "")
    if not isinstance(content, str):
        raise ValueError("File content must be text.")
    if file.get("format") == "json" or file.get("filename", "").lower().endswith(".json"):
        raw = json.loads(content)
        if isinstance(raw, dict):
            raw = raw.get("records")
        if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
            raise ValueError("JSON must be an array of objects or {records: [...]}.")
        headers = list(raw[0]) if raw else []
    else:
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("Duplicate column headers.")
        raw = list(reader)
        if any(None in row for row in raw):
            raise ValueError("A CSV row has more values than column headers.")
    if len(raw) > 100000:
        raise ValueError("Prototype limit: 100,000 rows per file.")
    mapping = file.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise ValueError("Column mapping must be an object.")
    normal = {canonical(h): h for h in headers}
    if len(normal) != len(headers):
        raise ValueError("Column headers become duplicates after normalisation.")
    columns = SCHEMAS[kind]["required"] + SCHEMAS[kind]["optional"]
    lookup = {c: mapping.get(c) or normal.get(c) for c in columns}
    if any(v and v not in headers for v in lookup.values()):
        raise ValueError("A mapped column does not exist in the file.")
    # Header-only CSV files are legitimate empty submissions.
    missing = [c for c in SCHEMAS[kind]["required"] if not lookup[c]]
    if missing and not (not raw and (file.get("format") == "json" or file.get("filename", "").lower().endswith(".json"))):
        raise ValueError("Missing columns: " + ", ".join(missing))
    rows = [{c: str(row.get(lookup[c], "") if lookup[c] else "").strip() if row.get(lookup[c]) is not None else "" for c in columns} for row in raw]
    return rows, headers


def validate_submission(files, period_start, period_end):
    issues, datasets, manifests = [], {}, []
    try:
        start, end = timestamp(period_start), timestamp(period_end)
        if start >= end:
            raise ValueError("Assessment start must precede its end.")
    except (TypeError, ValueError):
        return {"valid": False, "issues": [{"level": "error", "file": "period", "message": "Provide a valid start and end, with start before end."}], "datasets": {}, "manifests": []}
    if not isinstance(files, dict) or not files or "alerts" not in files:
        return {"valid": False, "issues": [{"level": "error", "file": "alerts", "message": "An alerts file is required."}], "datasets": {}, "manifests": []}
    for kind, file in files.items():
        try:
            rows, headers = parse_file(kind, file)
            datasets[kind] = rows
            manifests.append({"kind": kind, "filename": str(file.get("filename", kind))[:200], "rows": len(rows),
                              "sha256": hashlib.sha256(file.get("content", "").encode()).hexdigest(), "headers": headers})
        except (ValueError, TypeError, json.JSONDecodeError, csv.Error) as exc:
            issues.append({"level": "error", "file": kind, "message": str(exc)})
            continue
        seen = set()
        idfield = {"alerts": "alert_id", "cases": "case_id", "escalations": "escalation_id", "assets": "asset_id", "expectations": "expectation_id", "workflow": "event_id"}.get(kind)
        timezone_warning = False
        for index, row in enumerate(rows, 2):
            for field in SCHEMAS[kind]["required"]:
                if not row[field]:
                    issues.append({"level": "error", "file": kind, "row": index, "message": f"{field} is empty."})
            if idfield:
                if row[idfield] in seen:
                    issues.append({"level": "error", "file": kind, "row": index, "message": f"Duplicate {idfield}: {row[idfield]}."})
                seen.add(row[idfield])
            for field, val in row.items():
                if field.endswith("_at") and val:
                    try:
                        dt = timestamp(val)
                        if datetime.fromisoformat(val.replace("Z", "+00:00")).tzinfo is None:
                            timezone_warning = True
                        row[field] = dt.isoformat()
                        if field in ["created_at", "opened_at", "escalated_at"] and not start <= dt < end:
                            issues.append({"level": "warning", "file": kind, "row": index, "message": f"{field} is outside the assessment period; cross-period cases may be legitimate."})
                    except ValueError:
                        issues.append({"level": "error", "file": kind, "row": index, "message": f"Invalid date in {field}."})
            if "severity" in row and row["severity"]:
                row["severity"] = row["severity"].lower()
                if row["severity"] not in {"critical", "high", "medium", "low", "info"}:
                    issues.append({"level": "error", "file": kind, "row": index, "message": "Unknown severity."})
            for field in ["expected_monitoring", "approved_automation", "approved_exception", "investigation_required", "oversight_required", "recovery_validation_required"]:
                if row.get(field) and row[field].lower() not in {"true", "false", "1", "0", "yes", "no", "y", "n"}:
                    issues.append({"level": "error", "file": kind, "row": index, "message": f"{field} must be true or false."})
            if kind == "cases":
                row["status"] = row["status"].lower()
                if row["status"] not in {"open", "investigating", "escalated", "closed"}:
                    issues.append({"level": "error", "file": kind, "row": index, "message": "Status must be open, investigating, escalated or closed."})
                if row["status"] == "closed" and not row["closed_at"]:
                    issues.append({"level": "error", "file": kind, "row": index, "message": "Closed cases need closed_at."})
            if kind == "coverage" and row["coverage_status"].lower() not in {"active", "inactive", "unknown"}:
                issues.append({"level": "error", "file": kind, "row": index, "message": "Coverage status must be active, inactive or unknown."})
            if kind == 'workflow':
                if row['event_type'] not in {'investigation', 'response', 'oversight', 'recovery', 'remediation', 'escalation'}:
                    issues.append({'level': 'error', 'file': kind, 'row': index, 'message': 'Unknown workflow event_type.'})
                if row.get('result') and row['result'] not in {'success', 'failed', 'unknown'}:
                    issues.append({'level': 'error', 'file': kind, 'row': index, 'message': 'Workflow result must be success, failed or unknown.'})
            if kind == 'expectations':
                try:
                    if not 1 <= int(row['min_alerts']) <= 100000 or str(int(row['min_alerts'])) != row['min_alerts']:
                        raise ValueError()
                except ValueError:
                    issues.append({'level': 'error', 'file': kind, 'row': index, 'message': 'min_alerts must be an integer between 1 and 100000.'})
            if kind == "assets":
                row["criticality"] = row["criticality"].lower()
                if row["criticality"] not in {"critical", "high", "medium", "low"}:
                    issues.append({"level": "error", "file": kind, "row": index, "message": "Unknown asset criticality."})
            pairs = [("opened_at", "closed_at"), ("created_at", "acknowledged_at")]
            for left, right in pairs:
                if row.get(left) and row.get(right):
                    try:
                        if timestamp(row[right]) < timestamp(row[left]):
                            issues.append({"level": "error", "file": kind, "row": index, "message": f"{right} precedes {left}."})
                    except ValueError:
                        pass
            if len(issues) > 500:
                issues.append({"level": "error", "file": kind, "message": "Too many issues; showing the first 500. Correct the source and validate again."})
                break
        if timezone_warning:
            issues.append({"level": "warning", "file": kind, "message": "Dates without a timezone were interpreted as UTC."})
    for kind in SCHEMAS:
        if kind not in datasets:
            issues.append({"level": "info", "file": kind, "message": "Not submitted. Related capabilities will be marked not assessed."})
    return {"valid": not any(i["level"] == "error" for i in issues), "issues": issues, "datasets": datasets,
            "manifests": manifests, "row_count": sum(len(x) for x in datasets.values()), "schema_count": len(SCHEMAS), "completeness": round(len(datasets) / len(SCHEMAS) * 100)}


def analyse(datasets, policy, period_start, period_end):
    policy = validate_policy(policy)
    start, end = timestamp(period_start), timestamp(period_end)
    alerts = [a for a in datasets.get("alerts", []) if start <= timestamp(a["created_at"]) < end]
    cases = datasets.get("cases", [])
    case_map = {c["case_id"]: c for c in cases}
    links = defaultdict(list)
    for alert in alerts:
        if alert.get("case_id"):
            links[alert["case_id"]].append(alert)
    escalated = {e["case_id"] for e in datasets.get("escalations", [])}
    ranked = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    derived = []
    for original in cases:
        c = dict(original)
        linked = links[c["case_id"]]
        severities = [a["severity"] for a in linked] + ([c["severity"]] if c.get("severity") else [])
        c["severity"] = max(severities, key=lambda s: ranked[s]) if severities else "info"
        c["asset_id"] = c.get("asset_id") or (linked[0]["asset_id"] if linked else "")
        # Review only cases closed in this period, or open cases created here.
        event = c.get("closed_at") if c["status"] == "closed" else c["opened_at"]
        if event and start <= timestamp(event) < end:
            derived.append(c)
    closed = [c for c in derived if c["status"] == "closed"]
    findings, assessed, measures = [], {}, {}

    def record(detector, ids, summary, rationale, denominator, unit="cases", priority="high", extra=None):
        ids = list(dict.fromkeys(ids))
        if not ids:
            return
        meta = META[detector]
        findings.append({"detector": detector, "detector_version": ENGINE_VERSION, "title": meta["name"],
                         "domain": meta["domain"], "kind": meta["kind"], "priority": priority,
                         "summary": summary, "rationale": rationale, "evidence_ids": ids,
                         "affected_count": len(ids), "denominator": denominator, "unit": unit,
                         "rate": round(len(ids) / denominator * 100, 1) if denominator else None,
                         "limitations": ["Export completeness and entity policy must be confirmed by an examiner.", "A signal is not a confirmed operational failure."],
                         "context": extra or {}, "status": "pending"})

    assessed["fast_closure"] = "cases" in datasets
    eligible = [c for c in closed if c["severity"] in {"high", "critical"} and not truth(c.get("approved_automation")) and not truth(c.get("approved_exception"))]
    fast = [c for c in eligible if (timestamp(c["closed_at"]) - timestamp(c["opened_at"])).total_seconds() < policy["fast_closure_minutes"] * 60 and (len(c.get("investigation_notes", "").strip()) < 40 or not c.get("closure_reason"))]
    measures["fast_closure"] = {"affected": len(fast), "eligible": len(eligible)}
    record("fast_closure", [c["case_id"] for c in fast], f"{len(fast)} of {len(eligible)} eligible high-severity cases closed rapidly with weak evidence.",
           f"Closed in under {policy['fast_closure_minutes']} minutes with fewer than 40 note characters or no closure rationale. Approved automation and exceptions excluded.", len(eligible))

    assessed["missing_escalation"] = "cases" in datasets and "escalations" in datasets
    eligible = [c for c in closed if c["severity"] in policy["escalation_severities"] and not truth(c.get("approved_exception")) and not truth(c.get("approved_automation"))]
    missing = [c for c in eligible if c["case_id"] not in escalated] if assessed["missing_escalation"] else []
    measures["missing_escalation"] = {"affected": len(missing), "eligible": len(eligible)}
    record("missing_escalation", [c["case_id"] for c in missing], f"{len(missing)} of {len(eligible)} cases requiring escalation have no linked escalation.",
           "The configured policy requires escalation for: " + ", ".join(policy["escalation_severities"]) + ". Escalation records were submitted.", len(eligible))

    assessed["repeated_notes"] = "cases" in datasets
    groups = defaultdict(list)
    note_cases = [c for c in derived if len(c.get("investigation_notes", "")) >= 40 and not truth(c.get("approved_automation"))]
    for c in note_cases:
        normal = re.sub(r"\s+", " ", c["investigation_notes"].strip().lower())
        groups[normal].append(c)
    repetitions = [g for g in groups.values() if len(g) >= policy["repeated_note_minimum"] and len({c["asset_id"] for c in g if c["asset_id"]}) >= 2]
    note_ids = [c["case_id"] for g in repetitions for c in g]
    measures["repeated_notes"] = {"affected": len(note_ids), "eligible": len(note_cases)}
    record("repeated_notes", note_ids, f"{len(note_ids)} cases reuse investigation notes across different assets.",
           f"Identical notes after case/whitespace normalisation, in groups of at least {policy['repeated_note_minimum']}. Review whether notes contain case-specific evidence; playbook text may be legitimate.", len(note_cases), priority="medium", extra={"groups": len(repetitions), "comparison": "Exact normalised text; no external AI."})

    assessed["recurring_alerts"] = "cases" in datasets
    alert_groups = defaultdict(list)
    for a in alerts:
        alert_groups[(a["asset_id"], a["category"])].append(a)
    recurrence_ids, recurrence_groups = [], 0
    if assessed["recurring_alerts"]:
        for (asset, category), group in alert_groups.items():
            if len(group) >= policy["repeated_alert_minimum"] and not any(case_map.get(a.get("case_id"), {}).get("remediation_reference") for a in group):
                recurrence_ids.extend(a["alert_id"] for a in group)
                recurrence_groups += 1
    measures["recurring_alerts"] = {"affected": len(recurrence_ids), "eligible": len(alerts)}
    record("recurring_alerts", recurrence_ids, f"{recurrence_groups} asset/category groups recur without recorded remediation.",
           f"At least {policy['repeated_alert_minimum']} alerts in the period, with no remediation reference in linked cases. Repetition alone does not establish a failure.", len(alerts), unit="alerts", priority="medium", extra={"groups": recurrence_groups})

    assessed["coverage_gap"] = "assets" in datasets and "coverage" in datasets
    critical = [a for a in datasets.get("assets", []) if a["criticality"] == "critical" and truth(a["expected_monitoring"])]
    active = set()
    for c in datasets.get("coverage", []):
        age = (end - timestamp(c["last_seen_at"])).total_seconds() / 3600
        if c["coverage_status"].lower() == "active" and 0 <= age <= policy["coverage_stale_hours"]:
            active.add(c["asset_id"])
    coverage_ids = [a["asset_id"] for a in critical if a["asset_id"] not in active] if assessed["coverage_gap"] else []
    measures["coverage_gap"] = {"affected": len(coverage_ids), "eligible": len(critical)}
    record("coverage_gap", coverage_ids, f"{len(coverage_ids)} of {len(critical)} critical assets lack documented active coverage.",
           f"Asset inventory explicitly requires monitoring. No active source seen within {policy['coverage_stale_hours']} hours of period end. Coverage is assessed from source records, never from zero alert counts.", len(critical), unit="assets")

    assessed["unlinked_case"] = "cases" in datasets
    referred = [a for a in alerts if a.get("case_id")]
    unlinked = [a["alert_id"] for a in referred if a["case_id"] not in case_map] if assessed["unlinked_case"] else []
    measures["unlinked_case"] = {"affected": len(unlinked), "eligible": len(referred)}
    record("unlinked_case", unlinked, f"{len(unlinked)} alerts reference cases absent from the submitted export.",
           "An alert case_id could not be matched to the provided case file. Request export clarification before interpreting this as an investigation gap.", len(referred), unit="alerts", priority="medium")

    baseline = [c for c in closed if not truth(c.get("approved_automation")) and not truth(c.get("approved_exception"))]
    durations_baseline = [(timestamp(c["closed_at"]) - timestamp(c["opened_at"])).total_seconds() / 60 for c in baseline]
    assessed["closure_outlier"] = "cases" in datasets and len(baseline) >= 20
    q1, _, q3 = statistics.quantiles(durations_baseline, n=4, method="inclusive") if len(baseline) >= 20 else (None, None, None)
    fence = q1 - 1.5 * (q3 - q1) if q1 is not None else None
    eligible = [c for c in baseline if c["severity"] in {"high", "critical"}]
    outliers = [c for c in eligible if (timestamp(c["closed_at"]) - timestamp(c["opened_at"])).total_seconds() / 60 < fence and
                (len(c.get("investigation_notes", "").strip()) < 40 or not c.get("closure_reason"))] if assessed["closure_outlier"] else []
    measures["closure_outlier"] = {"affected": len(outliers), "eligible": len(eligible)}
    record("closure_outlier", [c["case_id"] for c in outliers], f"{len(outliers)} high-severity investigations are unusually short with weak evidence.",
           "Inclusive quartiles over non-approved closures; duration below Q1 − 1.5 × IQR, plus fewer than 40 note characters or missing closure rationale. Minimum baseline: 20 cases.", len(eligible), priority="medium",
           extra={"baseline_count": len(baseline), "q1_minutes": q1, "q3_minutes": q3, "lower_fence_minutes": fence})

    closed_ids = {c['case_id'] for c in closed}
    ack_rows = [a for a in alerts if a.get("acknowledged_at") and a.get("case_id") in closed_ids and
                not truth(case_map[a["case_id"]].get("approved_automation")) and not truth(case_map[a["case_id"]].get("approved_exception"))]
    sla = policy["acknowledgement_sla_minutes"]
    edge = [a for a in ack_rows if .9 * sla <= (timestamp(a["acknowledged_at"]) - timestamp(a["created_at"])).total_seconds() / 60 <= sla]
    assessed["sla_edge"] = "cases" in datasets and len(ack_rows) >= 20
    cluster = len(edge) >= 10 and len(edge) >= .5 * len(ack_rows)
    weak_edge = [a for a in edge if len(case_map[a["case_id"]].get("investigation_notes", "").strip()) < 40 or not case_map[a["case_id"]].get("closure_reason")] if cluster and assessed["sla_edge"] else []
    measures["sla_edge"] = {"affected": len(weak_edge), "eligible": len(ack_rows)}
    record("sla_edge", [a["alert_id"] for a in weak_edge], f"{len(weak_edge)} SLA-edge acknowledgements link to weak investigation evidence.",
           f"At least 10 and 50% of eligible acknowledgements occur in the final 10% of the {sla}-minute SLA; flagged linked cases have weak notes or missing closure rationale. Check workflow batching and timestamp semantics before interpreting KPI behaviour.", len(ack_rows), unit="alerts", priority="medium",
           extra={"eligible_acknowledgements": len(ack_rows), "edge_count": len(edge), "sla_minutes": sla, "window_start_minutes": .9 * sla, "intent_inferred": False})

    asset_map = {a['asset_id']: a for a in datasets.get('assets', [])}
    expectations = [e for e in datasets.get('expectations', []) if not truth(e.get('approved_exception')) and e['asset_id'] in asset_map]
    expected_assets = {e['asset_id'] for e in expectations}
    category_missing = {e['asset_id'] for e in expectations if len(alert_groups.get((e['asset_id'], e['category']), [])) < int(e['min_alerts'])}
    assessed['expected_category'] = 'expectations' in datasets and 'assets' in datasets
    measures['expected_category'] = {'affected': len(category_missing) if assessed['expected_category'] else 0, 'eligible': len(expected_assets)}
    if assessed['expected_category']:
        record('expected_category', sorted(category_missing), f"{len(category_missing)} assets have less activity than a justified submitted category expectation.",
               'Compare exact asset/category alert counts with the explicitly supplied minimum and expectation basis. Check exposure, test schedules and export completeness.', len(expected_assets), unit='assets', priority='medium')

    workflow = defaultdict(list)
    for event in datasets.get('workflow', []):
        workflow[event['case_id']].append(event)
    for key, requirement, event_type, domain in [('workflow_gap', 'investigation_required', 'investigation', 'Security operations'),
                                               ('oversight_gap', 'oversight_required', 'oversight', 'Governance'),
                                               ('recovery_gap', 'recovery_validation_required', 'recovery', 'Cyber resilience')]:
        eligible = [c for c in baseline if truth(c.get(requirement))]
        missing = []
        for c in eligible:
            events = [e for e in workflow[c['case_id']] if e['event_type'] == event_type and
                      timestamp(c['opened_at']) <= timestamp(e['performed_at']) <= timestamp(c['closed_at']) and
                      (event_type == 'recovery' or (e.get('evidence_reference') and
                       (event_type != 'oversight' or e.get('actor_role'))))]
            events.sort(key=lambda e: (timestamp(e['performed_at']), e['event_id']))
            # An older successful referenced test cannot override a later failed,
            # unknown or undocumented recovery test. Simultaneous latest events
            # must all demonstrate success; an ID tie-break is not chronology.
            latest = [e for e in events if timestamp(e['performed_at']) == timestamp(events[-1]['performed_at'])] if events else []
            if not events or (event_type == 'recovery' and any(e.get('result') != 'success' or not e.get('evidence_reference') for e in latest)):
                missing.append(c['case_id'])
        assessed[key] = 'workflow' in datasets and 'cases' in datasets
        measures[key] = {'affected': len(missing) if assessed[key] else 0, 'eligible': len(eligible)}
        if assessed[key]:
            record(key, missing, f"{len(missing)} of {len(eligible)} cases with an explicit {event_type} requirement lack acceptable completion evidence.",
                   f"The source case marks {requirement}=true. Require a referenced {event_type} event between case opening and closure" + (' with a reviewer role.' if event_type == 'oversight' else '; every test at the latest timestamp must have a reference and be marked success.' if event_type == 'recovery' else '.'),
                   len(eligible), priority='high' if event_type == 'recovery' else 'medium')

    profile_eligible, profiles = operational_profiles(baseline, links, workflow if 'workflow' in datasets else None)
    assessed['profile_outlier'] = 'cases' in datasets and bool(profile_eligible)
    measures['profile_outlier'] = {'affected': len(profiles), 'eligible': len(profile_eligible)}
    record('profile_outlier', list(profiles), f"{len(profiles)} cases show unusual combinations of operational evidence features.",
           'Discover feature combinations outside inclusive Q1/Q3 ± 1.5 IQR fences in same-severity cohorts of at least 20 non-approved closures. Require at least two unusual features. No failure label or intent is inferred.',
           len(profile_eligible), priority='medium', extra={'method': 'Unsupervised same-severity IQR profiles', 'record_profiles': profiles})

    assessed_measures = [min(1, m["affected"] / m["eligible"]) for k, m in measures.items() if assessed[k] and m["eligible"]]
    raw_score = sum(assessed_measures) / len(assessed_measures) * 100 if assessed_measures else None
    # Four decimal places keep a single affected record visible even at the
    # supported 100,000-row limit with all thirteen index terms included.
    score = round(raw_score, 4) if raw_score is not None else None
    domains = {}
    for domain in DOMAINS:
        rules = [d["id"] for d in DETECTORS if d["domain"] == domain and assessed[d["id"]] and measures[d["id"]]["eligible"]]
        rates = [min(1, measures[k]["affected"] / measures[k]["eligible"]) * 100 for k in rules]
        domains[domain] = round(sum(rates) / len(rates), 1) if rates else None
    durations = [(timestamp(c["closed_at"]) - timestamp(c["opened_at"])).total_seconds() / 60 for c in closed]
    daily = Counter(timestamp(a["created_at"]).date().isoformat() for a in alerts)
    return {"findings": findings, "metrics": {"alerts": len(alerts), "cases": len(derived), "closed_cases": len(closed),
            "critical_alerts": sum(a["severity"] == "critical" for a in alerts), "critical_assets": len(critical),
            "median_closure_minutes": round(statistics.median(durations), 1) if durations else None,
            "attention_score": score, "attention_calculation": {"unrounded_score": raw_score, "decimal_places": 4,
                "eligible_detector_count": len(assessed_measures)}, "domains": domains, "measures": measures, "assessed": assessed,
            "daily_activity": [{"date": day, "count": count} for day, count in sorted(daily.items())],
            "severity_distribution": dict(Counter(a["severity"] for a in alerts)), "engine_version": ENGINE_VERSION},
            "policy": policy}
