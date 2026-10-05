"""Read-only explanations of submitted populations; never rewrite historic results."""
from .analytics import SCHEMAS, timestamp, truth


def assessment_diagnostics(payload, period_start, period_end):
    data = payload['datasets']
    start, end = timestamp(period_start), timestamp(period_end)
    populations = []
    for kind, rows in data.items():
        field = {'alerts': 'created_at', 'escalations': 'escalated_at', 'workflow': 'performed_at'}.get(kind)
        if kind == 'cases':
            dates = [r.get('closed_at') if r['status'] == 'closed' else r['opened_at'] for r in rows]
            basis = 'Closed cases: closed_at; other cases: opened_at'
        elif field:
            dates = [r.get(field) for r in rows]
            basis = field
        else:
            dates = None
            basis = 'Snapshot context; coverage freshness is evaluated at period end' if kind == 'coverage' else 'Snapshot context; no interval exclusion'
        inside = sum(bool(v) and start <= timestamp(v) < end for v in dates) if dates is not None else None
        populations.append({'kind': kind, 'imported': len(rows), 'in_period': inside,
                            'out_of_period': len(rows) - inside if inside is not None else None, 'basis': basis})
    period_cases = [r for r in data.get('cases', []) if (v := r.get('closed_at') if r['status'] == 'closed' else r['opened_at']) and start <= timestamp(v) < end]
    approved = {r['case_id'] for r in period_cases if truth(r.get('approved_automation')) or truth(r.get('approved_exception'))}
    relationships = []
    for kind, field, target, target_field in [('alerts', 'case_id', 'cases', 'case_id'), ('alerts', 'asset_id', 'assets', 'asset_id'),
                                             ('cases', 'asset_id', 'assets', 'asset_id'), ('escalations', 'case_id', 'cases', 'case_id'),
                                             ('workflow', 'case_id', 'cases', 'case_id'), ('coverage', 'asset_id', 'assets', 'asset_id'),
                                             ('expectations', 'asset_id', 'assets', 'asset_id')]:
        ids = {r[target_field] for r in data.get(target, [])}
        missing = [r[field] for r in data.get(kind, []) if r.get(field) and r[field] not in ids]
        if missing:
            relationships.append({'source': kind, 'field': field, 'target': target, 'target_supplied': target in data,
                                  'affected_records': len(missing), 'missing_ids': sorted(set(missing))[:20]})
    return {'populations': populations, 'missing_files': [k for k in SCHEMAS if k not in data],
            'approved_control_cases': len(approved), 'relationships': relationships,
            'exclusion_note': 'Approved automation/exception cases are excluded only where each rule specifies. Approval is supplied evidence, not independently verified. See detector denominators and policy.',
            'relationship_note': 'Unresolved source references may indicate incomplete exports; these diagnostics are not additional detector findings.',
            'period_note': 'Start inclusive, end exclusive, UTC. Linked context outside this interval is retained; its presence alone does not make it eligible for a detector.'}
