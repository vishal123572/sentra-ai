"""Evidence-led presentation and reproducible review selection for stored assessments.

These helpers do not modify historic rule results or infer breach probabilities.
"""
import statistics
from collections import defaultdict
from .analytics import DETECTORS, META, timestamp, truth
from .patterns import operational_profiles

INPUTS = {"fast_closure": ["cases"], "missing_escalation": ["cases", "escalations"],
          "repeated_notes": ["cases"], "recurring_alerts": ["cases"],
          "coverage_gap": ["assets", "coverage"], "unlinked_case": ["cases"],
          "closure_outlier": ["cases"], "sla_edge": ["alerts", "cases"],
          "expected_category": ["alerts", "assets", "expectations"], "workflow_gap": ["cases", "workflow"],
          "oversight_gap": ["cases", "workflow"], "recovery_gap": ["cases", "workflow"], "profile_outlier": ["cases"]}
ID_FIELDS = {"cases": "case_id", "alerts": "alert_id", "assets": "asset_id"}
SEVERITY = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
SELECTION_METHOD = "One highest-ranked record per available unreviewed detector, then remaining records by score. Duplicate cases are merged. Severity contributes 0–40 points; highest signal priority 12 or 25; additional detectors 10 each, capped at 20. Ties use record kind and ID. This is a review heuristic, not a risk probability."


def file_types(submission):
    return tuple(sorted(m["kind"] for m in submission["validation"]["manifests"]))


def rate(submission, detector):
    metrics = submission["metrics"]
    measure = metrics["measures"].get(detector, {"affected": 0, "eligible": 0})
    if not metrics["assessed"].get(detector) or not measure["eligible"]:
        return None
    return measure["affected"] / measure["eligible"] * 100


def stored_engine(submission):
    return submission.get("engine_version") or submission["metrics"].get("engine_version")


def peer_benchmark(target, submissions):
    # Choose one newest matching assessment per OTHER entity. Historical periods
    # remain comparable even if that entity also supplied a later period.
    peers, seen = [], set()
    for other in submissions:
        if other["entity_id"] == target["entity_id"] or other["entity_id"] in seen:
            continue
        if (stored_engine(target) and stored_engine(other) == stored_engine(target) and
                all(other[key] == target[key] for key in ["sector", "size_band", "period_start", "period_end", "policy"]) and file_types(other) == file_types(target)):
            peers.append(other)
            seen.add(other["entity_id"])
    metrics = []
    for detector in DETECTORS:
        key = detector["id"]
        own = rate(target, key)
        values = [rate(peer, key) for peer in peers]
        values = [value for value in values if value is not None]
        median = statistics.median(values) if len(values) >= 2 and own is not None else None
        metrics.append({"detector": key, "name": detector["name"], "kind": detector["kind"],
                        "entity_rate": round(own, 1) if own is not None else None,
                        "peer_median": round(median, 1) if median is not None else None,
                        "difference_pp": round(own - median, 1) if median is not None else None,
                        "eligible_peers": len(values), "direction": "Higher affected rate means more evidence to examine."})
    eligible_mask = tuple(detector["id"] for detector in DETECTORS if rate(target, detector["id"]) is not None)
    indices = [peer["metrics"]["attention_score"] for peer in peers if peer["metrics"]["attention_score"] is not None and
               tuple(detector["id"] for detector in DETECTORS if rate(peer, detector["id"]) is not None) == eligible_mask]
    median = statistics.median(indices) if len(indices) >= 2 and target["metrics"]["attention_score"] is not None else None
    return {"available": len(peers) >= 2, "cohort_size": len(peers), "minimum_peers": 2,
            "index_median": median, "index_eligible_peers": len(indices), "metrics": metrics,
            "peers": [{"entity_id": p["entity_id"], "entity_name": p["entity_name"], "submission_id": p["id"]} for p in peers],
            "criteria": "Exact period, sector, size band, supplied file types, preserved policy and known stored engine version; one assessment per other entity. Each metric needs at least two peers with an eligible population. The index median also requires the same set of eligible detectors.",
            "limitation": "Contextual comparison only. Similar exports do not establish equal asset mix, monitoring quality or exposure; deviations are not proof of failure."}


def supervisory_summary(submission, findings):
    present = set(file_types(submission))
    drivers = []
    metrics = submission["metrics"]
    for detector in DETECTORS:
        key = detector["id"]
        measure = metrics["measures"].get(key, {"affected": 0, "eligible": 0})
        value = rate(submission, key)
        related = [f for f in findings if f["detector"] == key]
        drivers.append({**detector, **measure, "assessed": bool(metrics["assessed"].get(key)),
                        "rate": round(value, 2) if value is not None else None,
                        "included_in_index": value is not None,
                        "missing_inputs": [kind for kind in INPUTS[key] if kind not in present],
                        "assessment_note": "Not implemented in this stored engine version." if key not in metrics["measures"] else "Insufficient baseline or missing inputs." if not metrics["assessed"].get(key) else "No eligible records; excluded from the attention index." if not measure["eligible"] else "Assessed under the preserved policy.",
                        "finding_ids": [f["id"] for f in related],
                        "review_status": related[0]["status"] if related else None})
    active = [f for f in findings if f["status"] != "dismissed"]
    unreviewed = [f for f in findings if f["status"] in {"pending", "clarification"}]
    high = [f for f in active if f["priority"] == "high"]
    missing = [d["name"] for d in drivers if not d["assessed"]]
    level = "High" if high else "Moderate" if active else "Incomplete" if missing else "No open signals"
    reason = (f"{len(high)} non-dismissed high-priority finding groups need examination or follow-up." if high else
              f"{len(active)} non-dismissed finding groups need examination or follow-up." if active else
              "Some capabilities cannot be assessed from the supplied files." if missing else
              "No non-dismissed rule findings. This does not establish effective SOC operation.")
    return {"level": level, "reason": reason, "attention_score": metrics["attention_score"], "drivers": drivers,
            "execution_gaps": [f["id"] for f in active if f["kind"] == "Execution gap"],
            "negative_space": [f["id"] for f in active if f["kind"] == "Negative space"],
            "unreviewed_groups": len(unreviewed), "missing_capabilities": missing,
            "index_terms": sum(d["included_in_index"] for d in drivers),
            "method": "Equal mean of affected/eligible rates for assessable detectors with eligible records, " +
                      (f"stored to {metrics['attention_calculation']['decimal_places']} decimal places. " if metrics.get('attention_calculation') else "stored rounded to an integer by the historical engine. ") +
                      "Missing inputs and empty eligible populations are excluded, not set to zero. Review decisions do not rewrite the stored index.",
            "level_method": "High: at least one non-dismissed high-priority finding; Moderate: other non-dismissed findings; Incomplete: unassessed capabilities without open findings; otherwise No open signals. This workload label is separate from the index and is not a resilience rating."}


class EvidenceIndex:
    def __init__(self, payload, period_start, period_end):
        self.data, self.policy = payload["datasets"], payload["policy"]
        self.start, self.end = timestamp(period_start), timestamp(period_end)
        self.maps = {kind: {record[ID_FIELDS[kind]]: record for record in self.data.get(kind, [])} for kind in ID_FIELDS}
        self.positions = {kind: {record[ID_FIELDS[kind]]: index + 1 for index, record in enumerate(self.data.get(kind, []))} for kind in ID_FIELDS}
        self.alerts_by_case, self.alerts_by_asset = defaultdict(list), defaultdict(list)
        self.groups, self.coverage, self.escalations, self.notes = (defaultdict(list) for _ in range(4))
        self.workflow = defaultdict(list)
        self.expectations = defaultdict(list)
        for e in self.data.get('workflow', []):
            self.workflow[e['case_id']].append(e)
        for e in self.data.get('expectations', []):
            self.expectations[e['asset_id']].append(e)
        self.closure_baseline = [(timestamp(c["closed_at"]) - timestamp(c["opened_at"])).total_seconds() / 60
                                 for c in self.data.get("cases", []) if c["status"] == "closed" and c.get("closed_at") and
                                 self.start <= timestamp(c["closed_at"]) < self.end and not truth(c.get("approved_automation")) and not truth(c.get("approved_exception"))]
        for alert in self.data.get("alerts", []):
            self.alerts_by_case[alert.get("case_id")].append(alert)
            self.alerts_by_asset[alert["asset_id"]].append(alert)
            if self.start <= timestamp(alert["created_at"]) < self.end:
                self.groups[(alert["asset_id"], alert["category"])].append(alert)
        for coverage in self.data.get("coverage", []):
            self.coverage[coverage["asset_id"]].append(coverage)
        for escalation in self.data.get("escalations", []):
            self.escalations[escalation["case_id"]].append(escalation)
        for case in self.data.get("cases", []):
            event = case.get("closed_at") if case["status"] == "closed" else case["opened_at"]
            if event and self.start <= timestamp(event) < self.end and len(case.get("investigation_notes", "")) >= 40 and not truth(case.get("approved_automation")):
                self.notes[" ".join(case["investigation_notes"].strip().lower().split())].append(case)
        derived = [c | {'severity': self.severity('cases', c)} for c in self.data.get('cases', []) if c['status'] == 'closed' and c.get('closed_at') and self.start <= timestamp(c['closed_at']) < self.end]
        period_links = {key: [a for a in values if self.start <= timestamp(a['created_at']) < self.end] for key, values in self.alerts_by_case.items()}
        _, self.profile_details = operational_profiles(derived, period_links, self.workflow if 'workflow' in self.data else None)

    def severity(self, kind, record):
        values = [record.get("severity", "info")]
        if kind == "assets":
            values.append(record.get("criticality", "info"))
        if kind == "cases":
            values += [alert["severity"] for alert in self.alerts_by_case[record["case_id"]] if self.start <= timestamp(alert["created_at"]) < self.end]
        return max(values, key=lambda value: SEVERITY.get(value, 0))

    def explain(self, detector, record):
        key, policy = detector, self.policy
        observed = []
        if key == "fast_closure":
            minutes = (timestamp(record["closed_at"]) - timestamp(record["opened_at"])).total_seconds() / 60
            observed = [f"Effective severity: {self.severity('cases', record)}; status: {record['status']}.",
                        f"Closed after {minutes:.2f} minutes; threshold is less than {policy['fast_closure_minutes']} minutes.",
                        f"Investigation notes: {len(record.get('investigation_notes', '').strip())} characters; closure rationale {'present' if record.get('closure_reason') else 'absent'}.",
                        f"Approved automation: {truth(record.get('approved_automation'))}; approved exception: {truth(record.get('approved_exception'))}."]
            expected = "High/critical rapid closures should have sufficient investigation evidence or a documented approved exception/automation."
            check = "Check the investigation timeline, case-specific evidence and approved closure procedure."
        elif key == "missing_escalation":
            observed = [f"Effective severity: {self.severity('cases', record)}; status: {record['status']}.",
                        f"Linked escalation records in the submitted export: {len(self.escalations[record['case_id']])}.",
                        f"Policy requires escalation for: {', '.join(policy['escalation_severities'])}."]
            expected = "A linked escalation record for an eligible closed case, unless approved automation or an exception applies."
            check = "Confirm escalation export completeness, the entity policy and any exception or alternative escalation channel."
        elif key == "repeated_notes":
            matches = self.notes[" ".join(record.get("investigation_notes", "").strip().lower().split())]
            observed = [f"Identical normalised narrative in {len(matches)} cases across {len({case.get('asset_id') or self.asset_id('cases', case) for case in matches})} assets; minimum group is {policy['repeated_note_minimum']}.",
                        "Matching case IDs (first 20): " + ", ".join(case["case_id"] for case in matches[:20])]
            expected = "Investigation records should demonstrate case-specific work; legitimate playbook text may repeat."
            check = "Compare the actual notes and corroborating records; exact text reuse alone does not prove superficial investigation."
        elif key == "recurring_alerts":
            matches = self.groups[(record["asset_id"], record["category"])]
            refs = [self.maps["cases"].get(alert.get("case_id"), {}).get("remediation_reference") for alert in matches]
            observed = [f"Asset {record['asset_id']}; category {record['category']}; {len(matches)} alerts in the period; threshold {policy['repeated_alert_minimum']}.",
                        f"Recorded remediation references in linked cases: {sum(bool(ref) for ref in refs)}.",
                        "Alert IDs (first 20): " + ", ".join(alert["alert_id"] for alert in matches[:20])]
            expected = "Recurring asset/category alerts should have documented investigation and appropriate remediation follow-up."
            check = "Check tuning, benign repetition, linked cases and external change records before concluding remediation failed."
        elif key == "coverage_gap":
            rows = self.coverage[record["asset_id"]]
            observed = [f"Inventory criticality: {record['criticality']}; expected monitoring: {truth(record['expected_monitoring'])}.",
                        f"Submitted coverage records: {len(rows)}; freshness threshold {policy['coverage_stale_hours']} hours before period end."]
            for row in rows[:20]:
                age = (self.end - timestamp(row["last_seen_at"])).total_seconds() / 3600
                observed.append(f"{row['monitoring_source']}: {row['coverage_status']}; last seen {row['last_seen_at']}; age at period end {age:.1f} hours.")
            expected = "At least one active coverage record, with last-seen age between zero and the policy freshness threshold, for this critical asset requiring monitoring."
            check = "Confirm inventory expectations, the snapshot date and coverage export completeness. Zero alert counts are not used to infer this gap."
        elif key == "closure_outlier":
            q1, _, q3 = statistics.quantiles(self.closure_baseline, n=4, method="inclusive")
            minutes = (timestamp(record["closed_at"]) - timestamp(record["opened_at"])).total_seconds() / 60
            observed = [f"Baseline: {len(self.closure_baseline)} non-approved closures; Q1 {q1:.2f}, Q3 {q3:.2f} minutes.",
                        f"Lower fence Q1 − 1.5 × IQR: {q1 - 1.5 * (q3-q1):.2f} minutes; observed duration: {minutes:.2f} minutes.",
                        f"Effective severity: {self.severity('cases', record)}; notes {len(record.get('investigation_notes', '').strip())} characters; rationale {'present' if record.get('closure_reason') else 'absent'}."]
            expected = "An unusually short high-severity investigation should have case-specific supporting evidence. Minimum baseline: 20 non-approved closures."
            check = "Check legitimate workflow differences and case complexity; a duration outlier is not proof of inadequate work."
        elif key == "sla_edge":
            sla = policy['acknowledgement_sla_minutes']
            case = self.maps['cases'].get(record.get('case_id'), {})
            minutes = (timestamp(record['acknowledged_at']) - timestamp(record['created_at'])).total_seconds() / 60
            observed = [f"Acknowledged after {minutes:.2f} minutes; SLA-edge window {sla*.9:.2f}–{sla:.2f} minutes.",
                        f"Linked case: {record.get('case_id')}; notes {len(case.get('investigation_notes', '').strip())} characters; rationale {'present' if case.get('closure_reason') else 'absent'}."]
            expected = "Meeting acknowledgement timing should be accompanied by meaningful investigation evidence. The submission must contain at least 20 eligible acknowledgements linked to in-period closed cases, with at least 10 and half in the SLA-edge window."
            check = "Check batching, timestamp semantics and the documented SLA. This pattern raises a KPI question; it does not establish gaming or intent."
        elif key == 'expected_category':
            expectations = [e for e in self.expectations[record['asset_id']] if not truth(e.get('approved_exception'))]
            observed = [f"{e['category']}: {len(self.groups[(e['asset_id'], e['category'])])} submitted alerts; expected at least {e['min_alerts']}. Basis: {e['expectation_basis']}" for e in expectations]
            expected = 'The asset/category minimum explicitly stated in the expectation export, with a documented basis and any approved exception.'
            check = 'Confirm the expectation, assessment period and export completeness. Expected activity is entity-specific; zero alerts alone do not establish a blind spot.'
        elif key in {'workflow_gap', 'oversight_gap', 'recovery_gap'}:
            requirement, event_type = {'workflow_gap': ('investigation_required', 'investigation'), 'oversight_gap': ('oversight_required', 'oversight'), 'recovery_gap': ('recovery_validation_required', 'recovery')}[key]
            events = [e for e in self.workflow[record['case_id']] if e['event_type'] == event_type]
            observed = [f"Source case {requirement}: {record.get(requirement)}; {len(events)} submitted {event_type} events."]
            observed += [f"{e['event_id']}: {e['performed_at']}; role {e.get('actor_role') or 'absent'}; reference {e.get('evidence_reference') or 'absent'}; result {e.get('result') or 'not supplied'}." for e in events[:20]]
            expected = f"A referenced {event_type} event within the opening/closure interval" + (' with reviewer role.' if key == 'oversight_gap' else '; each test at the latest timestamp must have a reference and be explicitly successful.' if key == 'recovery_gap' else '.')
            check = 'Confirm the explicit source requirement, workflow export completeness, timestamps and supporting document. Record presence does not prove effective work.'
        elif key == 'profile_outlier':
            profile = self.profile_details.get(record['case_id'], {})
            observed = [f"Same-severity cohort: {profile.get('severity_cohort')}; baseline {profile.get('baseline_count')} cases."]
            observed += [f"{feature}: {value['observed']}; inclusive IQR interval [{value['lower']:.2f}, {value['upper']:.2f}]; Q1 {value['q1']:.2f}, Q3 {value['q3']:.2f}." for feature, value in profile.get('unusual_features', {}).items()]
            expected = 'Review combinations of at least two unusual evidence features relative to a same-severity cohort of at least 20 cases.'
            check = 'Interpret the candidate pattern, legitimate case complexity and collection differences. No predefined failure label, misconduct or breach probability is inferred.'
        else:
            observed = [f"Alert references case {record.get('case_id')}; that ID is absent from the submitted case export."]
            expected = "A submitted investigation record matching the alert's explicit case reference."
            check = "Request the missing case record or corrected export; absent submitted evidence does not prove investigation never occurred."
        return {"expected": expected, "observed": observed, "examiner_check": check}

    def asset_id(self, kind, record):
        return record.get("asset_id") or (self.alerts_by_case[record.get("case_id")][0]["asset_id"] if kind == "cases" and self.alerts_by_case[record.get("case_id")] else "")

    def candidates(self, findings):
        candidates = {}
        for finding in findings:
            if finding["status"] not in {"pending", "clarification"}:
                continue
            source_kind = finding["unit"]
            for evidence_id in finding["evidence_ids"]:
                source = self.maps[source_kind].get(evidence_id)
                if not source:
                    continue
                kind, record = source_kind, source
                if kind == "alerts" and source.get("case_id") in self.maps["cases"]:
                    kind, record = "cases", self.maps["cases"][source["case_id"]]
                record_id = record[ID_FIELDS[kind]]
                item = candidates.setdefault((kind, record_id), {"kind": kind, "record_id": record_id, "asset_id": self.asset_id(kind, record),
                    "severity": self.severity(kind, record), "signals": {}, "record": record})
                signal = item["signals"].setdefault(finding["detector"], {"finding_id": finding["id"], "detector": finding["detector"],
                    "title": finding["title"], "kind": finding["kind"], "priority": finding["priority"], "status": finding["status"], "evidence_ids": []})
                signal["evidence_ids"].append(evidence_id)
        for item in candidates.values():
            item["signals"] = list(item["signals"].values())
            severity_points = SEVERITY.get(item["severity"], 0) * 10
            priority_points = 25 if any(signal["priority"] == "high" for signal in item["signals"]) else 12
            overlap_points = min(20, (len(item["signals"]) - 1) * 10)
            item["score"] = severity_points + priority_points + overlap_points
            item["score_breakdown"] = {"severity": severity_points, "highest_signal_priority": priority_points, "additional_detectors": overlap_points}
        return sorted(candidates.values(), key=lambda item: (-item["score"], item["kind"], item["record_id"]))

    def selection(self, findings, count=8):
        candidates = self.candidates(findings)
        selected, used = [], set()
        for detector in DETECTORS:
            item = next((candidate for candidate in candidates if (candidate["kind"], candidate["record_id"]) not in used and any(signal["detector"] == detector["id"] for signal in candidate["signals"])), None)
            # An already selected overlapping case represents this detector too.
            if any(any(signal["detector"] == detector["id"] for signal in chosen["signals"]) for chosen in selected):
                continue
            if item and len(selected) < count:
                selected.append(item | {"selection_reason": f"Highest-ranked available record representing {detector['name']}."})
                used.add((item["kind"], item["record_id"]))
        for item in candidates:
            if len(selected) >= count:
                break
            if (item["kind"], item["record_id"]) not in used:
                selected.append(item | {"selection_reason": "Next highest-ranked remaining record after detector coverage."})
                used.add((item["kind"], item["record_id"]))
        for index, item in enumerate(selected, 1):
            item["rank"] = index
            item.pop("record")
        return {"records": selected, "population": len(candidates), "budget": count, "selected_count": len(selected),
                "covered_detectors": sorted({signal["detector"] for item in selected for signal in item["signals"]}),
                "method": SELECTION_METHOD, "limitation": "Targets known, unreviewed rule signals. Include an independent sample to look for weaknesses outside these detectors. Assets and alerts remain review items where no case is available."}
