"""Comparison with adjudicated expert labels; unlabelled records never become negatives."""
import csv
import hashlib
import io
import json
import zipfile
from .analytics import timestamp
from .supervisory import EvidenceIndex, ID_FIELDS


def in_review_period(index, kind, record):
    if kind == 'assets':
        return True
    event = record['created_at'] if kind == 'alerts' else record.get('closed_at') if record['status'] == 'closed' else record['opened_at']
    return bool(event and index.start <= timestamp(event) < index.end)


def blinded_package(payload, submission_id, start, end):
    out, csv_out = io.BytesIO(), io.StringIO(newline='')
    writer = csv.writer(csv_out)
    writer.writerow(['unit', 'record_id', 'expert_concern', 'adjudicated', 'split', 'expert_reason', 'issue_id'])
    index = EvidenceIndex(payload, start, end)
    for kind, field in ID_FIELDS.items():
        for record in payload['datasets'].get(kind, []):
            if in_review_period(index, kind, record):
                writer.writerow([kind, record[field], '', 'false', 'held_out', '', ''])
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('labels.csv', csv_out.getvalue())
        archive.writestr('records.json', json.dumps({'submission_id': submission_id, 'period_start': start, 'period_end': end,
                                                   'datasets': payload['datasets'], 'policy': payload['policy']}, indent=2))
        archive.writestr('README.txt', 'Review independently before inspecting detector output. Reconcile expert disagreements and document reasons. Set adjudicated=true only after agreement. Use held_out for evaluation and tuning for excluded development data. Leave unreviewed labels blank. Detector findings, index and recommendation rankings are intentionally omitted. Synthetic labels do not prove real-world efficacy.\n')
    return out.getvalue()


def parse_labels(content, filename):
    rows = json.loads(content) if filename.lower().endswith('.json') else list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))
    if not isinstance(rows, list) or len(rows) > 100000 or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Provide up to 100,000 label rows.')
    return rows


def evaluate(payload, findings, start, end, labels, budget=8):
    if not isinstance(budget, int) or isinstance(budget, bool) or not 1 <= budget <= 100:
        raise ValueError('Review budget must be a whole number from 1 to 100.')
    index = EvidenceIndex(payload, start, end)
    truth = {}
    excluded = 0
    for row in labels:
        if not isinstance(row, dict) or any(isinstance(row.get(field), (dict, list)) for field in ('split', 'adjudicated', 'unit', 'record_id', 'expert_concern')):
            raise ValueError('Label fields must be scalar values, with one object per record.')
        if row.get('split') != 'held_out' or row.get('adjudicated') not in {'true', True, '1'}:
            excluded += 1
            continue
        kind, identifier = row.get('unit'), row.get('record_id')
        if kind not in ID_FIELDS or identifier not in index.maps[kind]:
            raise ValueError('An adjudicated label references an unknown record in this submission.')
        if not in_review_period(index, kind, index.maps[kind][identifier]):
            raise ValueError('An adjudicated label references a record outside the assessment period.')
        value = row.get('expert_concern')
        if value not in {'true', 'false', True, False, '1', '0'}:
            raise ValueError('Adjudicated expert_concern must be true or false.')
        key = (kind, identifier)
        if key in truth:
            raise ValueError('Duplicate or unresolved expert labels; reconcile before evaluating.')
        truth[key] = value in {'true', True, '1'}
    if not truth:
        raise ValueError('No adjudicated held-out labels. Complete expert review first.')
    predicted = set()
    flagged_assets = {identifier for finding in findings if finding['unit'] == 'assets' for identifier in finding['evidence_ids']}
    for finding in findings:
        kind = finding['unit']
        for identifier in finding['evidence_ids']:
            predicted.add((kind, identifier))
            if kind == 'alerts':
                c = index.maps['alerts'].get(identifier, {}).get('case_id')
                if c in index.maps['cases']:
                    predicted.add(('cases', c))
    # Match the independent-sample exclusion scope, including cases whose
    # primary asset differs from another asset in their linked alerts.
    for alert in index.data.get('alerts', []):
        if alert['asset_id'] in flagged_assets and alert.get('case_id') in index.maps['cases']:
            predicted.add(('cases', alert['case_id']))
    for case in index.data.get('cases', []):
        if index.asset_id('cases', case) in flagged_assets:
            predicted.add(('cases', case['case_id']))
    tp = sum(value and key in predicted for key, value in truth.items())
    fp = sum(not value and key in predicted for key, value in truth.items())
    fn = sum(value and key not in predicted for key, value in truth.items())
    tn = len(truth)-tp-fp-fn
    ranked = index.candidates([f | {'status': 'pending'} for f in findings])
    priority = [(r['kind'], r['record_id']) for r in ranked if (r['kind'], r['record_id']) in truth][:budget]
    # Independent comparison samples the same labelled scope without excluding flags.
    baseline = sorted(truth, key=lambda key: hashlib.sha256(('SATSA-validation-seed-42'+repr(key)).encode()).hexdigest())[:budget]
    yield_row = lambda ids: {'reviewed': len(ids), 'concerns_found': sum(truth[key] for key in ids), 'record_ids': [{'unit': k, 'record_id': i} for k, i in ids]}
    return {'labelled_records': len(truth), 'excluded_non_adjudicated_or_tuning': excluded,
            'confusion': {'true_positive': tp, 'false_positive': fp, 'false_negative': fn, 'true_negative': tn},
            'precision': tp/(tp+fp) if tp+fp else None, 'recall': tp/(tp+fn) if tp+fn else None,
            'review_budget': budget, 'prioritised_review': yield_row(priority), 'hash_baseline_review': yield_row(baseline),
            'engine_version': payload['engine_version'],
            'limitations': ['Results cover only adjudicated held-out labels supplied by the user; unlabelled records are excluded.',
                           'Record-level signals include direct flags and linked alert/asset flags. These are not issue-group metrics.',
                           'Prioritised yield uses descending record priority in the labelled scope; the separate examiner recommendation balances detector coverage.',
                           'Review yield uses at most the budget in the labelled scope. A single seeded baseline is not a statistical significance test.',
                           'Synthetic labels do not establish effectiveness comparable to expert review on genuine SOC exports.']}
