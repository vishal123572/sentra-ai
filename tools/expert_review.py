#!/usr/bin/env python3
"""Prepare blinded review records or evaluate independently adjudicated labels."""
import argparse
import csv
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.storage import Store
from app.service import Service
from app.evaluation import parse_labels, evaluate, in_review_period
from app.supervisory import ID_FIELDS, EvidenceIndex


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--submission', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--labels', help='Without labels, prepare a blinded review package.')
    p.add_argument('--budget', type=int, default=8)
    args = p.parse_args()
    if not Path(args.database).is_file() or Path(args.output).exists():
        p.error('Use an existing database and a new output path.')
    service = Service(Store(args.database))
    row, payload, findings = service._assessment_source(args.submission)
    output = Path(args.output)
    if args.labels:
        path = Path(args.labels)
        result = evaluate(payload, findings, row['period_start'], row['period_end'], parse_labels(path.read_text(), path.name), args.budget)
        output.write_text(json.dumps(result, indent=2))
    else:
        output.mkdir(parents=True)
        index = EvidenceIndex(payload, row['period_start'], row['period_end'])
        with (output/'labels.csv').open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['unit', 'record_id', 'expert_concern', 'adjudicated', 'split', 'expert_reason', 'issue_id'])
            for kind, field in ID_FIELDS.items():
                for record in payload['datasets'].get(kind, []):
                    if in_review_period(index, kind, record):
                        w.writerow([kind, record[field], '', 'false', 'held_out', '', ''])
        # Deliberately omit detector findings, index and recommendation rankings.
        (output/'records.json').write_text(json.dumps({'submission_id': args.submission, 'period_start': row['period_start'], 'period_end': row['period_end'], 'datasets': payload['datasets'], 'policy': payload['policy']}, indent=2))
        (output/'README.txt').write_text('Review records independently before inspecting detector output. Reconcile expert disagreements, record reasoning, and set adjudicated=true only after agreement. Use held_out for evaluation and tuning for excluded development data. Leave unreviewed labels blank. Never call synthetic labels real expert validation.\n')
    print(f'Expert review artifact ready: {output}')


if __name__ == '__main__':
    main()
