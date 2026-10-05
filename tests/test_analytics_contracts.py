"""Analytical contracts, supplied control exports, and synthetic expert arithmetic.

All persistence checks use temporary databases. Synthetic labels test calculation
behaviour only; they are not evidence of real-world expert efficacy.
"""
import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import timedelta
from pathlib import Path

from app.analytics import DEFAULT_POLICY, DETECTORS, ENGINE_VERSION, analyse, timestamp, validate_submission
from app.demo import make_submission
from app.evaluation import blinded_package, evaluate, parse_labels
from app.service import Service, html_report
from app.storage import Store
from app.supervisory import EvidenceIndex, peer_benchmark, supervisory_summary


class AnalyticsContractTests(unittest.TestCase):
    def datasets(self, profile='healthy'):
        payload, labels = make_submission(profile)
        validated = validate_submission(payload['files'], payload['period_start'], payload['period_end'])
        self.assertTrue(validated['valid'], validated['issues'])
        return payload, labels, validated['datasets']

    def run_analysis(self, data, payload, policy=None):
        return analyse(data, policy or DEFAULT_POLICY, payload['period_start'], payload['period_end'])

    def test_supplied_testenergy_is_exactly_one_exploratory_case_not_manufactured_failures(self):
        folder = Path(__file__).parent / 'fixtures' / 'testenergy'
        files = {path.stem: {'filename': path.name, 'content': path.read_bytes().decode('utf-8')} for path in folder.glob('*.csv')}
        validated = validate_submission(files, '2026-09-01T00:00:00Z', '2026-10-01T00:00:00Z')
        self.assertTrue(validated['valid'], validated['issues'])
        self.assertEqual(validated['row_count'], 381)
        self.assertEqual({kind: len(rows) for kind, rows in validated['datasets'].items()},
                         {'alerts': 160, 'cases': 160, 'assets': 12, 'coverage': 17, 'escalations': 32})
        result = analyse(validated['datasets'], DEFAULT_POLICY, '2026-09-01T00:00:00Z', '2026-10-01T00:00:00Z')
        self.assertEqual([(f['detector'], f['evidence_ids']) for f in result['findings']], [('profile_outlier', ['TE-CS-0022'])])
        profile = result['findings'][0]['context']['record_profiles']['TE-CS-0022']
        self.assertEqual(profile['severity_cohort'], 'medium')
        self.assertEqual(profile['baseline_count'], 39)
        self.assertEqual(set(profile['unusual_features']), {'closure_minutes', 'note_characters'})
        self.assertEqual(profile['unusual_features']['note_characters']['observed'], 1170)
        self.assertGreater(result['metrics']['attention_score'], 0)
        self.assertLess(result['metrics']['attention_score'], 1)
        self.assertEqual(sum(not value for value in result['metrics']['assessed'].values()), 4)
        calculation = result['metrics']['attention_calculation']
        self.assertEqual(result['metrics']['attention_score'], round(calculation['unrounded_score'], calculation['decimal_places']))

    def test_all_thirteen_detectors_have_valid_denominators_and_planted_source_evidence(self):
        seen = set()
        for scenario in ['execution', 'coverage']:
            payload, labels, data = self.datasets(scenario)
            result = self.run_analysis(data, payload)
            for finding in result['findings']:
                key = finding['detector']
                seen.add(key)
                self.assertEqual(finding['detector_version'], ENGINE_VERSION)
                self.assertEqual(finding['affected_count'], len(set(finding['evidence_ids'])))
                self.assertLessEqual(finding['affected_count'], finding['denominator'])
                self.assertEqual(finding['denominator'], result['metrics']['measures'][key]['eligible'])
                source_ids = {row[{'cases': 'case_id', 'alerts': 'alert_id', 'assets': 'asset_id'}[finding['unit']]] for row in data[finding['unit']]}
                self.assertTrue(set(finding['evidence_ids']) <= source_ids)
                if key in labels:
                    self.assertEqual(set(finding['evidence_ids']), set(labels[key]))
                self.assertIn('not a confirmed', ' '.join(finding['limitations']))
        self.assertEqual(seen, {d['id'] for d in DETECTORS})

    def test_absent_export_is_unassessed_but_explicit_empty_export_can_show_absence(self):
        payload, _, data = self.datasets()
        missing = copy.deepcopy(data)
        missing.pop('escalations')
        absent_result = self.run_analysis(missing, payload)
        missing['escalations'] = []
        empty_result = self.run_analysis(missing, payload)
        self.assertFalse(absent_result['metrics']['assessed']['missing_escalation'])
        self.assertFalse(any(f['detector'] == 'missing_escalation' for f in absent_result['findings']))
        self.assertTrue(empty_result['metrics']['assessed']['missing_escalation'])
        finding = next(f for f in empty_result['findings'] if f['detector'] == 'missing_escalation')
        self.assertEqual(finding['affected_count'], finding['denominator'])

    def test_approved_case_controls_exclude_all_applicable_failure_checks_and_profiles(self):
        for field in ['approved_automation', 'approved_exception']:
            payload, _, data = self.datasets('execution')
            for case in data['cases']:
                case[field] = 'true'
            result = self.run_analysis(data, payload)
            excluded_detectors = {'fast_closure', 'missing_escalation', 'closure_outlier', 'sla_edge',
                                  'workflow_gap', 'oversight_gap', 'recovery_gap', 'profile_outlier'}
            self.assertTrue(all(result['metrics']['measures'][key]['eligible'] == 0 for key in excluded_detectors))
            self.assertFalse(excluded_detectors & {f['detector'] for f in result['findings']})

    def test_custom_escalation_policy_changes_eligible_population_and_is_preserved(self):
        payload, _, data = self.datasets()
        data['escalations'] = []
        policy = DEFAULT_POLICY | {'escalation_severities': ['medium']}
        result = self.run_analysis(data, payload, policy)
        finding = next(f for f in result['findings'] if f['detector'] == 'missing_escalation')
        expected = {c['case_id'] for c in data['cases'] if c['severity'] == 'medium' and c['approved_automation'] != 'true'}
        self.assertEqual(set(finding['evidence_ids']), expected)
        self.assertEqual(finding['denominator'], len(expected))
        self.assertEqual(result['policy'], policy)

    def test_closed_period_boundaries_use_closure_time_and_end_is_exclusive(self):
        payload, _, data = self.datasets()
        data = {kind: [] for kind in data}
        start, end = payload['period_start'], payload['period_end']
        data['cases'] = [dict(case_id='AT-START', opened_at=(timestamp(start) - timedelta(seconds=30)).isoformat(),
                              closed_at=start, status='closed', severity='critical', asset_id='A', investigation_notes='', closure_reason=''),
                         dict(case_id='AT-END', opened_at=(timestamp(end) - timedelta(seconds=30)).isoformat(),
                              closed_at=end, status='closed', severity='critical', asset_id='A', investigation_notes='', closure_reason='')]
        result = self.run_analysis(data, payload)
        self.assertEqual(result['metrics']['closed_cases'], 1)
        self.assertEqual(next(f for f in result['findings'] if f['detector'] == 'fast_closure')['evidence_ids'], ['AT-START'])

    def test_latest_unreferenced_recovery_failure_cannot_be_hidden_by_older_success(self):
        payload, _, data = self.datasets()
        event = next(e for e in data['workflow'] if e['event_type'] == 'recovery')
        case = next(c for c in data['cases'] if c['case_id'] == event['case_id'])
        failed = event | {'event_id': 'LATEST-FAIL', 'performed_at': case['closed_at'], 'result': 'failed', 'evidence_reference': ''}
        data['workflow'].append(failed)
        finding = next(f for f in self.run_analysis(data, payload)['findings'] if f['detector'] == 'recovery_gap')
        self.assertIn(case['case_id'], finding['evidence_ids'])
        failed.update(result='success', evidence_reference='verified-latest-recovery')
        self.assertFalse(any(f['detector'] == 'recovery_gap' for f in self.run_analysis(data, payload)['findings']))

    def test_simultaneous_recovery_conflict_is_unresolved_without_ordering_evidence(self):
        payload, _, data = self.datasets()
        event = next(e for e in data['workflow'] if e['event_type'] == 'recovery')
        data['workflow'].append(event | {'event_id': 'AAA-FAILED', 'result': 'failed'})
        finding = next(f for f in self.run_analysis(data, payload)['findings'] if f['detector'] == 'recovery_gap')
        self.assertIn(event['case_id'], finding['evidence_ids'])

    def test_workflow_requirements_are_explicit_and_oversight_needs_role_and_reference(self):
        payload, _, data = self.datasets()
        oversight = next(e for e in data['workflow'] if e['event_type'] == 'oversight')
        oversight['actor_role'] = ''
        finding = next(f for f in self.run_analysis(data, payload)['findings'] if f['detector'] == 'oversight_gap')
        self.assertIn(oversight['case_id'], finding['evidence_ids'])
        case = next(c for c in data['cases'] if c['case_id'] == oversight['case_id'])
        case['oversight_required'] = 'false'
        self.assertFalse(any(f['detector'] == 'oversight_gap' for f in self.run_analysis(data, payload)['findings']))

    def summary(self):
        payload, _, data = self.datasets()
        result = self.run_analysis(data, payload)
        return {'id': 'TARGET', 'entity_id': 'A', 'entity_name': 'A', 'sector': 'Energy', 'size_band': 'medium',
                'period_start': payload['period_start'], 'period_end': payload['period_end'],
                'policy': result['policy'], 'metrics': result['metrics'], 'engine_version': ENGINE_VERSION,
                'validation': {'manifests': [{'kind': kind} for kind in data]}}

    def test_peer_comparison_excludes_different_or_unknown_stored_engine_and_self(self):
        target = self.summary()
        peers = [copy.deepcopy(target) | {'id': 'P' + str(i), 'entity_id': str(i), 'entity_name': str(i)} for i in range(3)]
        peers[0]['engine_version'] = '1.2.0'
        peers[1].pop('engine_version')
        peers[1]['metrics'].pop('engine_version')
        result = peer_benchmark(target, peers + [target])
        self.assertEqual(result['cohort_size'], 1)
        self.assertFalse(result['available'])
        self.assertTrue(all(m['peer_median'] is None for m in result['metrics']))
        peers[0]['engine_version'] = ENGINE_VERSION
        result = peer_benchmark(target, peers + [target])
        self.assertTrue(result['available'])
        self.assertEqual(result['cohort_size'], 2)
        self.assertEqual(result['index_median'], 0)

    def test_historical_integer_index_stays_stored_and_empty_denominators_are_explained(self):
        target = self.summary()
        target['metrics'].pop('attention_calculation')
        target['metrics']['attention_score'] = 0
        target['metrics']['measures']['fast_closure'] = {'affected': 0, 'eligible': 0}
        summary = supervisory_summary(target, [])
        self.assertEqual(summary['attention_score'], 0)
        self.assertIn('historical engine', summary['method'])
        driver = next(d for d in summary['drivers'] if d['id'] == 'fast_closure')
        self.assertFalse(driver['included_in_index'])
        self.assertIsNone(driver['rate'])
        self.assertIn('No eligible records', driver['assessment_note'])

    def test_expert_confusion_counts_exclusions_budget_and_unlabelled_scope(self):
        payload, _, data = self.datasets()
        stored = {'datasets': data, 'policy': DEFAULT_POLICY, 'engine_version': ENGINE_VERSION}
        cases = [c['case_id'] for c in data['cases'][1:7]]
        findings = [{'id': 'TEST-FINDING', 'detector': 'fast_closure', 'title': 'Synthetic arithmetic fixture',
                     'kind': 'Execution gap', 'priority': 'high', 'unit': 'cases', 'evidence_ids': cases[:2], 'status': 'dismissed'}]
        labels = [{'unit': 'cases', 'record_id': identifier, 'expert_concern': concern, 'adjudicated': 'true', 'split': 'held_out'}
                  for identifier, concern in zip(cases[:4], ['true', 'false', 'true', 'false'])]
        labels += [labels[0] | {'record_id': cases[4], 'split': 'tuning'},
                   labels[0] | {'record_id': cases[5], 'adjudicated': 'false'}]
        result = evaluate(stored, findings, payload['period_start'], payload['period_end'], labels, 2)
        self.assertEqual(result['confusion'], {'true_positive': 1, 'false_positive': 1, 'false_negative': 1, 'true_negative': 1})
        self.assertEqual((result['precision'], result['recall']), (.5, .5))
        self.assertEqual(result['labelled_records'], 4)
        self.assertEqual(result['excluded_non_adjudicated_or_tuning'], 2)
        self.assertEqual(result['prioritised_review']['reviewed'], 2)
        self.assertEqual(result['prioritised_review']['concerns_found'], 1)
        self.assertEqual(result, evaluate(stored, findings, payload['period_start'], payload['period_end'], labels, 2))
        negatives = [labels[3]]
        undefined = evaluate(stored, [], payload['period_start'], payload['period_end'], negatives)
        self.assertIsNone(undefined['precision'])
        self.assertIsNone(undefined['recall'])

    def test_expert_predictions_include_secondary_asset_links_consistently_with_sampling(self):
        payload, _, data = self.datasets()
        case = data['cases'][1]
        secondary_asset = data['assets'][2]['asset_id']
        next(a for a in data['alerts'] if a['case_id'] == case['case_id'])['asset_id'] = secondary_asset
        stored = {'datasets': data, 'policy': DEFAULT_POLICY, 'engine_version': ENGINE_VERSION}
        findings = [{'id': 'ASSET-FLAG', 'detector': 'coverage_gap', 'title': 'Synthetic linked-scope fixture',
                     'kind': 'Negative space', 'priority': 'high', 'unit': 'assets', 'evidence_ids': [secondary_asset], 'status': 'pending'}]
        labels = [{'unit': 'cases', 'record_id': case['case_id'], 'expert_concern': 'true', 'adjudicated': 'true', 'split': 'held_out'}]
        result = evaluate(stored, findings, payload['period_start'], payload['period_end'], labels)
        self.assertEqual(result['confusion']['true_positive'], 1)
        self.assertEqual(result['confusion']['false_negative'], 0)

    def test_blinded_package_has_raw_evidence_but_no_detector_results_or_rankings(self):
        payload, _, data = self.datasets('execution')
        stored = {'datasets': data, 'policy': DEFAULT_POLICY, 'engine_version': ENGINE_VERSION,
                  'findings': 'SECRET DETECTOR CONCLUSIONS', 'metrics': {'attention_score': 99}}
        with zipfile.ZipFile(io.BytesIO(blinded_package(stored, 'SYNTHETIC', payload['period_start'], payload['period_end']))) as archive:
            records = json.loads(archive.read('records.json'))
            self.assertEqual(set(records), {'submission_id', 'period_start', 'period_end', 'datasets', 'policy'})
            self.assertEqual(records['datasets'], data)
            labels = list(csv.DictReader(io.StringIO(archive.read('labels.csv').decode())))
            self.assertEqual(len(labels), len(data['alerts']) + len(data['cases']) + len(data['assets']))
            self.assertTrue(all(not row['expert_concern'] and row['adjudicated'] == 'false' for row in labels))
            self.assertNotIn(b'SECRET DETECTOR CONCLUSIONS', b''.join(archive.read(name) for name in archive.namelist()))

    def test_expert_label_bom_and_malformed_fields_return_validation_errors(self):
        rows = parse_labels('\ufeffunit,record_id,adjudicated,split,expert_concern\ncases,C1,true,held_out,true\n', 'labels.csv')
        self.assertEqual(rows[0]['unit'], 'cases')
        payload, _, data = self.datasets()
        stored = {'datasets': data, 'policy': DEFAULT_POLICY, 'engine_version': ENGINE_VERSION}
        with self.assertRaisesRegex(ValueError, 'scalar'):
            evaluate(stored, [], payload['period_start'], payload['period_end'], [{'adjudicated': []}])

    def test_expert_label_hash_results_and_audit_survive_restart_and_report(self):
        payload, _, _ = self.datasets('execution')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'temporary.sqlite3'
            service = Service(Store(path))
            entity = service.entity_create({'name': 'Synthetic arithmetic validation', 'sector': 'Energy'}, 'examiner')['id']
            submission = service.ingest(payload | {'entity_id': entity}, 'examiner')['id']
            labels = [{'unit': 'cases', 'record_id': 'ATL-09-CASE-0006', 'expert_concern': 'true',
                       'adjudicated': 'true', 'split': 'held_out', 'expert_reason': 'Synthetic planted fixture only.'}]
            content = json.dumps(labels)
            before = service._assessment_source(submission)[2]
            result = service.evaluate(submission, {'filename': 'labels.json', 'content': content}, 'synthetic-reviewer')
            self.assertEqual(result['label_sha256'], hashlib.sha256(content.encode()).hexdigest())
            restarted = Service(Store(path))
            report = restarted.report(submission_id=submission)
            self.assertEqual(report['expert_comparisons'][0], result)
            self.assertIn(result['label_sha256'], html_report(report))
            self.assertEqual(restarted._assessment_source(submission)[2], before)
            self.assertTrue(restarted.store.verify_audit()['valid'])
            with restarted.store.connect() as db:
                audit = json.loads(db.execute("SELECT detail FROM audit WHERE action='expert_comparison.created'").fetchone()[0])
            self.assertEqual(audit['label_sha256'], result['label_sha256'])


if __name__ == '__main__':
    unittest.main()
