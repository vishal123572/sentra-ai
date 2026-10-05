import hashlib
import csv
from contextlib import closing
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from app.analytics import DEFAULT_POLICY, analyse, parse_file, validate_submission
from app.demo import make_submission
from app.evaluation import evaluate, blinded_package
from app.service import Service
from app.storage import Store
from tools.import_bundle import bundle, sqlite_snapshot, api_snapshot


class ExtendedTests(unittest.TestCase):
    def datasets(self, profile='execution'):
        payload, labels = make_submission(profile)
        result = validate_submission(payload['files'], payload['period_start'], payload['period_end'])
        self.assertTrue(result['valid'], result['issues'])
        return payload, labels, result['datasets']

    def test_explicit_workflow_and_category_expectations_detect_planted_ids(self):
        for profile, keys in [('execution', ['workflow_gap', 'oversight_gap']), ('coverage', ['expected_category', 'recovery_gap'])]:
            payload, labels, datasets = self.datasets(profile)
            result = analyse(datasets, DEFAULT_POLICY, payload['period_start'], payload['period_end'])
            findings = {f['detector']: f for f in result['findings']}
            for key in keys:
                self.assertEqual(set(findings[key]['evidence_ids']), set(labels[key]))

    def test_missing_expectation_and_workflow_exports_remain_unassessed(self):
        payload, _, data = self.datasets('coverage')
        data.pop('expectations'); data.pop('workflow')
        result = analyse(data, DEFAULT_POLICY, payload['period_start'], payload['period_end'])
        for key in ['expected_category', 'workflow_gap', 'oversight_gap', 'recovery_gap']:
            self.assertFalse(result['metrics']['assessed'][key])
            self.assertNotIn(key, [f['detector'] for f in result['findings']])

    def test_unusual_profile_discovers_a_candidate_beyond_named_failure_rules(self):
        payload, _, data = self.datasets()
        result = analyse(data, DEFAULT_POLICY, payload['period_start'], payload['period_end'])
        profile = next(f for f in result['findings'] if f['detector'] == 'profile_outlier')
        detail = profile['context']['record_profiles']['ATL-09-CASE-0152']
        self.assertGreaterEqual(detail['baseline_count'], 20)
        self.assertGreaterEqual(len(detail['unusual_features']), 2)
        for key in ['fast_closure', 'missing_escalation', 'repeated_notes', 'closure_outlier', 'sla_edge']:
            self.assertFalse(any('ATL-09-CASE-0152' in f['evidence_ids'] for f in result['findings'] if f['detector'] == key))

    def test_late_or_unreferenced_workflow_does_not_satisfy_required_step(self):
        payload, _, data = self.datasets('healthy')
        event = next(e for e in data['workflow'] if e['event_type'] == 'investigation')
        event['performed_at'] = payload['period_end']
        result = analyse(data, DEFAULT_POLICY, payload['period_start'], payload['period_end'])
        self.assertIn(event['case_id'], next(f for f in result['findings'] if f['detector'] == 'workflow_gap')['evidence_ids'])

    def test_approved_expectation_exception_excludes_the_asset(self):
        payload, _, data = self.datasets('coverage')
        for row in data['expectations']:
            row['approved_exception'] = 'true'
        result = analyse(data, DEFAULT_POLICY, payload['period_start'], payload['period_end'])
        self.assertEqual(result['metrics']['measures']['expected_category']['eligible'], 0)
        self.assertNotIn('expected_category', [f['detector'] for f in result['findings']])

    def test_invalid_new_schema_fields_block_assessment(self):
        payload, _, _ = self.datasets()
        rows, _ = parse_file('expectations', payload['files']['expectations'])
        rows[0]['min_alerts'] = '-1'
        payload['files']['expectations'] = {'format': 'json', 'content': json.dumps(rows)}
        self.assertFalse(validate_submission(payload['files'], payload['period_start'], payload['period_end'])['valid'])

    def test_sqlite_export_is_read_only_and_bundle_excludes_unneeded_fields(self):
        payload, _, data = self.datasets('healthy')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'source.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE alerts(alert_id TEXT,asset_id TEXT,category TEXT,severity TEXT,created_at TEXT,customer_secret TEXT)')
                a = data['alerts'][0]
                db.execute('INSERT INTO alerts VALUES(?,?,?,?,?,?)', (a['alert_id'], a['asset_id'], a['category'], a['severity'], a['created_at'], 'PRIVATE'))
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            value = bundle(sqlite_snapshot(path), payload['period_start'], payload['period_end'])
            self.assertNotIn('PRIVATE', json.dumps(value))
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaises(ValueError):
                sqlite_snapshot(path, {'alerts': 'alerts; DROP TABLE alerts'})

    def test_api_adapter_rejects_public_and_redirectable_credential_urls(self):
        for url in ['https://example.com/data', 'http://8.8.8.8/data', 'http://user:password@127.0.0.1/data', 'file:///tmp/data']:
            with self.assertRaises(ValueError):
                api_snapshot(url)

    def test_expert_comparison_excludes_unlabelled_and_tuning_and_persists(self):
        payload, _, _ = self.datasets()
        with tempfile.TemporaryDirectory() as folder:
            service = Service(Store(Path(folder)/'satsa.sqlite3'))
            entity = service.entity_create({'name': 'Comparison', 'sector': 'Energy'}, 'examiner')['id']
            submission = service.ingest(payload | {'entity_id': entity}, 'examiner')['id']
            row, stored, findings = service._assessment_source(submission)
            labels = [dict(unit='cases', record_id='ATL-09-CASE-0006', expert_concern='true', adjudicated='true', split='held_out'),
                      dict(unit='cases', record_id='ATL-09-CASE-0001', expert_concern='true', adjudicated='true', split='held_out'),
                      dict(unit='cases', record_id='ATL-09-CASE-0007', expert_concern='false', adjudicated='false', split='held_out'),
                      dict(unit='cases', record_id='ATL-09-CASE-0008', expert_concern='false', adjudicated='true', split='tuning')]
            result = service.evaluate(submission, {'filename': 'labels.json', 'content': json.dumps(labels)}, 'expert')
            self.assertEqual(result['labelled_records'], 2)
            self.assertEqual(result['confusion']['true_positive'], 1)
            self.assertEqual(result['confusion']['false_negative'], 1)
            self.assertEqual(result['recall'], .5)
            self.assertEqual(result['excluded_non_adjudicated_or_tuning'], 2)
            self.assertEqual(service.report(submission_id=submission)['expert_comparisons'][0]['id'], result['id'])
            self.assertTrue(service.store.verify_audit()['valid'])
            with self.assertRaises(ValueError):
                evaluate(stored, findings, row['period_start'], row['period_end'], labels[:1]*2)

    def test_blinded_labels_and_comparison_keep_the_assessment_period(self):
        payload, _, data = self.datasets('healthy')
        old_case = data['cases'][0]
        old_case['opened_at'] = '2026-08-01T00:00:00Z'
        old_case['closed_at'] = '2026-08-01T01:00:00Z'
        stored = {'datasets': data, 'policy': DEFAULT_POLICY, 'engine_version': '1.2.0'}
        archive = blinded_package(stored, 'TEST', payload['period_start'], payload['period_end'])
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            labels = list(csv.DictReader(io.StringIO(z.read('labels.csv').decode())))
            self.assertFalse(any(r['unit'] == 'cases' and r['record_id'] == old_case['case_id'] for r in labels))
            self.assertNotIn('findings', json.loads(z.read('records.json')))
        label = dict(unit='cases', record_id=old_case['case_id'], expert_concern='true', adjudicated='true', split='held_out')
        with self.assertRaisesRegex(ValueError, 'outside the assessment period'):
            evaluate(stored, [], payload['period_start'], payload['period_end'], [label])
