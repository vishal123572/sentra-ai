import copy
import tempfile
import unittest
from pathlib import Path
from app.ai import analyse_ai
from app.analytics import validate_submission
from app.demo import make_submission
from app.service import Service, html_report
from app.storage import Store


class AiTests(unittest.TestCase):
    def data(self):
        payload, _ = make_submission('execution')
        data = validate_submission(payload['files'], payload['period_start'], payload['period_end'])['datasets']
        return payload, data

    def test_model_trains_reproducibly_and_explains_candidates(self):
        payload, data = self.data()
        first = analyse_ai(data, payload['period_start'], payload['period_end'])
        self.assertEqual(first['status'], 'assessed')
        self.assertGreater(first['trained_cohorts'], 0)
        self.assertGreater(first['flagged_count'], 0)
        self.assertFalse(first['included_in_attention_index'])
        reordered = copy.deepcopy(data)
        reordered['cases'].reverse()
        self.assertEqual(first, analyse_ai(reordered, payload['period_start'], payload['period_end']))
        for record in first['candidates']:
            self.assertLess(record['decision_score'], 0)
            self.assertTrue(record['features'])
            self.assertTrue(all('score_change_at_median' in feature for feature in record['features']))

    def test_small_cohorts_and_approved_cases_do_not_get_anomaly_labels(self):
        payload, data = self.data()
        data['cases'] = data['cases'][:4]
        self.assertEqual(analyse_ai(data, payload['period_start'], payload['period_end'])['status'], 'insufficient_data')
        payload, data = self.data()
        for record in data['cases']:
            record['approved_exception'] = 'true'
        result = analyse_ai(data, payload['period_start'], payload['period_end'])
        self.assertEqual(result['flagged_count'], 0)
        self.assertEqual(result['trained_cohorts'], 0)

    def test_training_provenance_survives_store_reopen_and_report(self):
        payload, _ = make_submission('execution')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ai.sqlite3'
            service = Service(Store(path))
            entity = service.entity_create({'name': 'AI persistence test', 'sector': 'Energy', 'size_band': 'medium'}, 'test')
            result = service.ingest(payload | {'entity_id': entity['id']}, 'test')
            stored = Service(Store(path)).assessment(result['id'])['submission']['metrics']['ai_analysis']
            self.assertEqual(stored, result['metrics']['ai_analysis'])
            self.assertTrue(all(len(cohort['training_sha256']) == 64 for cohort in stored['cohorts'] if cohort['status'] == 'trained'))
            self.assertIn('Isolation Forest', html_report(service.report()))
