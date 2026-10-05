"""Reproducible synthetic exports; never represented as real CSE data."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .service import ServiceError
from .analytics import SCHEMAS

ENTITIES = [
    ("SYNTHETIC · Meridian Energy", "healthy", "MER"),
    ("SYNTHETIC · Atlas Grid", "execution", "ATL"),
    ("SYNTHETIC · Northstar Power", "coverage", "NOR"),
]


def csv_text(kind, records):
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=SCHEMAS[kind]["required"] + SCHEMAS[kind]["optional"])
    w.writeheader()
    w.writerows(records)
    return out.getvalue()


def make_submission(profile="execution", prefix="ATL", month=9, rows=160):
    if profile == "coverage" and month == 9 and rows == 160:
        rows = 40  # Deliberate activity decline; volume alone is not a coverage finding.
    start = datetime(2026, month, 1, tzinfo=timezone.utc)
    end = datetime(2026, month + 1, 1, tzinfo=timezone.utc)
    data = {k: [] for k in SCHEMAS}
    labels = {"fast_closure": [], "missing_escalation": [], "repeated_notes": [], "coverage_gap": [], "unlinked_case": [], "closure_outlier": [], "sla_edge": [], "recurring_alerts": [], 'expected_category': [], 'workflow_gap': [], 'oversight_gap': [], 'recovery_gap': []}
    assets = [f"{prefix}-ASSET-{i:02}" for i in range(1, 13)]
    for i, asset in enumerate(assets):
        data["assets"].append({"asset_id": asset, "asset_type": "server" if i < 9 else "gateway", "criticality": "critical" if i < 6 else "high", "expected_monitoring": "true", "name": f"Synthetic system {i+1}"})
        category = ['Authentication anomaly', 'Endpoint detection', 'Privilege change', 'Network policy event'][i % 4]
        absent = profile == 'coverage' and month == 9 and i in [0, 1]
        data['expectations'].append({'expectation_id': f'{prefix}-EXPECT-{i}', 'asset_id': asset, 'category': 'Scheduled security test' if absent else category, 'min_alerts': '1', 'expectation_basis': 'Synthetic monthly test schedule expects one event in this category.', 'approved_exception': 'false'})
        if absent:
            labels['expected_category'].append(asset)
        gap = profile == "coverage" and i in [0, 1, 2] and month == 9
        if gap:
            labels["coverage_gap"].append(asset)
        else:
            data["coverage"].append({"asset_id": asset, "monitoring_source": "endpoint-export", "coverage_status": "active", "last_seen_at": (end - timedelta(hours=3)).isoformat()})
    for i in range(rows):
        case_id = f"{prefix}-{month:02}-CASE-{i+1:04}"
        alert_id = f"{prefix}-{month:02}-ALERT-{i+1:04}"
        asset = assets[i % len(assets)]
        severity = "critical" if i % 5 == 0 else "high" if i % 3 == 0 else "medium"
        opened = start + timedelta(days=i % 27, hours=7 + i % 10, minutes=i % 45)
        closed = opened + timedelta(minutes=45 + i % 11)
        notes = f"Reviewed process tree for event {i+1}; correlated endpoint and authentication records on {asset}. Verified source ownership, recorded timeline and checked related connections."
        reason, remediation = "Documented investigation supports closure; follow-up recorded.", f"SYN-CHANGE-{month}-{i+1}"
        automation = "true" if i % 31 == 0 else "false"
        if automation == "true":
            closed, notes, reason = opened + timedelta(seconds=15), "", "Approved duplicate suppression playbook"
        weak = profile == "execution" and month == 9 and i in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
        if weak:
            closed, notes, reason = opened + timedelta(seconds=35), "Checked. Closed.", ""
            labels["fast_closure"].append(case_id)
            labels["closure_outlier"].append(case_id)
        if profile == "execution" and month == 9 and 101 <= i <= 150 and automation != "true":
            notes, reason = "Acknowledged. Closed.", ""
            if i == 110:
                closed = opened + timedelta(minutes=7)
                labels["closure_outlier"].append(case_id)
        no_escalation = (profile == "execution" and i % 5 == 0 and 5 <= i <= (70 if month == 9 else 20)) or (profile == "coverage" and month == 9 and i in [5, 10, 15])
        if no_escalation and automation != "true":
            labels["missing_escalation"].append(case_id)
        if profile == "execution" and month == 9 and 61 <= i <= 74 and automation != "true":
            notes = "Reviewed the security alert and performed standard checks. No suspicious activity identified. The case was closed according to the documented procedure."
            labels["repeated_notes"].append(case_id)
        if profile == "execution" and month == 9 and 90 <= i <= 99:
            asset, remediation = assets[10], ""
            labels['recurring_alerts'].append(alert_id)
        if profile == 'healthy' and month == 9 and i == 20:
            notes = f"Reviewed event {i+1} on {asset}. A follow-up ticket exists, but the system restore test is still failing and the vendor fix is pending. Confirm recovery evidence before relying on this closure."
            reason = "Closed with vendor follow-up pending; recovery evidence not attached."
        if profile == 'execution' and month == 9 and i == 151:
            closed = opened + timedelta(hours=8)
            notes = (f'Extended evidence narrative for unusual event {i} on {asset}. ' * 40).strip()
        category = "Suspicious service creation" if profile == "execution" and month == 9 and 90 <= i <= 99 else ["Authentication anomaly", "Endpoint detection", "Privilege change", "Network policy event"][i % 4]
        data["cases"].append({"case_id": case_id, "opened_at": opened.isoformat(), "closed_at": closed.isoformat(), "status": "closed", "asset_id": asset, "severity": severity,
                              "investigation_notes": notes, "closure_reason": reason, "approved_automation": automation, "approved_exception": "false", "remediation_reference": remediation,
                              'investigation_required': 'true', 'oversight_required': 'true' if severity == 'critical' else 'false', 'recovery_validation_required': 'true' if i % 10 == 0 else 'false'})
        if automation != 'true':
            investigation_missing = profile == 'execution' and month == 9 and i in [5, 10, 15]
            oversight_missing = profile == 'execution' and month == 9 and i in [20, 25]
            recovery_failed = profile == 'coverage' and month == 9 and i in [10, 20]
            duration = (closed-opened).total_seconds()
            for event_type, fraction in [('investigation', .2), ('response', .4), ('oversight', .6), ('recovery', .8)]:
                if event_type == 'oversight' and severity != 'critical' or event_type == 'recovery' and i % 10 != 0:
                    continue
                if event_type == 'investigation' and investigation_missing:
                    labels['workflow_gap'].append(case_id)
                    continue
                if event_type == 'oversight' and oversight_missing:
                    labels['oversight_gap'].append(case_id)
                    continue
                if event_type == 'recovery' and recovery_failed:
                    labels['recovery_gap'].append(case_id)
                data['workflow'].append({'event_id': f'{case_id}-{event_type}', 'case_id': case_id, 'event_type': event_type,
                                         'performed_at': (opened+timedelta(seconds=duration*fraction)).isoformat(), 'actor_role': 'Duty lead' if event_type == 'oversight' else 'Analyst',
                                         'evidence_reference': f'SYN-EVIDENCE-{i}-{event_type}', 'result': 'failed' if event_type == 'recovery' and recovery_failed else 'success'})
        referenced_id = case_id
        if profile == "coverage" and month == 9 and i in [20, 21, 22]:
            referenced_id = f"{prefix}-ABSENT-{i}"
            labels["unlinked_case"].append(alert_id)
        alert_created = opened - timedelta(minutes=30) if profile == 'execution' and month == 9 else opened
        ack = alert_created + (timedelta(minutes=29.5) if profile == 'execution' and month == 9 else timedelta(seconds=10))
        if profile == 'execution' and month == 9 and automation != 'true' and (len(notes.strip()) < 40 or not reason):
            labels['sla_edge'].append(alert_id)
        data["alerts"].append({"alert_id": alert_id, "asset_id": asset, "category": category, "severity": severity, "created_at": alert_created.isoformat(), "acknowledged_at": ack.isoformat(), "case_id": referenced_id})
        if severity == "critical" and not no_escalation and automation != "true":
            data["escalations"].append({"escalation_id": f"{prefix}-{month}-ESC-{i}", "case_id": case_id, "escalated_at": (opened + timedelta(minutes=5)).isoformat(), "destination_role": "Duty lead"})
    files = {k: {"filename": k + ".csv", "format": "csv", "content": csv_text(k, records)} for k, records in data.items()}
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "files": files}, labels


def load_demo(service, actor):
    loaded, skipped = 0, 0
    state = service.state()
    names = {e["name"]: e["id"] for e in state["entities"]}
    for name, profile, prefix in ENTITIES:
        entity_id = names.get(name)
        if not entity_id:
            entity_id = service.entity_create({"name": name, "sector": "Energy", "size_band": "medium"}, actor)["id"]
        for month in [8, 9]:
            data, labels = make_submission(profile, prefix, month)
            try:
                service.ingest(data | {"entity_id": entity_id}, actor)
                loaded += 1
            except ServiceError as exc:
                if exc.status != 409:
                    raise
                skipped += 1
    return {"loaded": loaded, "skipped": skipped, "message": "Synthetic demonstration data is ready. Existing assessments and decisions were preserved."}


def write_samples(destination):
    destination = Path(destination)
    for name, profile, prefix in ENTITIES:
        payload, labels = make_submission(profile, prefix)
        folder = destination / profile
        folder.mkdir(parents=True, exist_ok=True)
        for kind, file in payload["files"].items():
            (folder / f"{kind}.csv").write_text(file["content"], encoding="utf-8")
        (folder / "expected-signals.json").write_text(json.dumps({"synthetic": True, "entity": name, "period_start": payload["period_start"], "period_end": payload["period_end"], "planted_evidence_ids": labels}, indent=2), encoding="utf-8")
    return str(destination)
