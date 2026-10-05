import json
import tempfile
import unittest
from pathlib import Path
from app.analytics import DEFAULT_POLICY
from app.demo import load_demo, make_submission
from app.service import Service, ServiceError, csv_report, html_report
from app.storage import Store


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "satsa.sqlite3"
        self.service = Service(Store(self.path))
        self.entity_id = self.service.entity_create({"name": "Test Entity", "sector": "Energy", "size_band": "medium"}, "examiner")["id"]

    def tearDown(self):
        self.temp.cleanup()

    def ingest(self):
        payload, _ = make_submission()
        return self.service.ingest(payload | {"entity_id": self.entity_id}, "examiner")

    def test_duplicate_submission_rejected_without_new_findings(self):
        self.ingest()
        before = len(self.service.state()["findings"])
        with self.assertRaises(ServiceError) as caught:
            self.ingest()
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.service.state()["findings"]), before)

    def test_review_persists_and_prevents_overwriting_concurrent_review(self):
        self.ingest()
        f = self.service.state()["findings"][0]
        self.service.review(f["id"], {"version": 1, "status": "clarification", "comment": "Please confirm export completeness."}, "reviewer")
        restarted = Service(Store(self.path))
        full = restarted.finding(f["id"])
        self.assertEqual(full["status"], "clarification")
        self.assertEqual(full["reviews"][0]["actor"], "reviewer")
        self.assertEqual(full["version"], 2)
        with self.assertRaises(ServiceError) as caught:
            restarted.review(f["id"], {"version": 1, "status": "dismissed", "comment": "Old decision."}, "other")
        self.assertEqual(caught.exception.status, 409)

    def test_audit_detects_modified_event(self):
        self.ingest()
        self.assertTrue(self.service.store.verify_audit()["valid"])
        with self.service.store.transaction() as db:
            db.execute("UPDATE audit SET actor='tampered' WHERE sequence=1")
        self.assertFalse(self.service.store.verify_audit()["valid"])

    def test_existing_policy_snapshot_is_immutable(self):
        s = self.ingest()
        self.service.entity_policy(self.entity_id, DEFAULT_POLICY | {"fast_closure_minutes": 15}, "examiner")
        self.assertEqual(self.service.submission(s["id"])["policy"]["fast_closure_minutes"], 2)

    def test_evidence_pagination_and_reproducible_sample(self):
        s = self.ingest()
        f = next(f for f in self.service.state()["findings"] if f["detector"] == "fast_closure")
        first = self.service.finding(f["id"], 0, 3)
        second = self.service.finding(f["id"], 3, 3)
        self.assertEqual(len(first["evidence"]["records"]), 3)
        self.assertTrue(set(r["case_id"] for r in first["evidence"]["records"]).isdisjoint(r["case_id"] for r in second["evidence"]["records"]))
        self.assertEqual(self.service.sample(s["id"]), self.service.sample(s["id"]))

    def test_report_escapes_html_and_csv_formula(self):
        self.ingest()
        report = self.service.report()
        report["findings"][0]["comment"] = '<script>alert(1)</script>'
        report["findings"][0]["entity_name"] = '=HYPERLINK("x")'
        self.assertNotIn('<script>alert(1)</script>', html_report(report))
        self.assertIn('&lt;script&gt;', html_report(report))
        self.assertIn("'=HYPERLINK", csv_report(report))

    def test_demo_loader_is_idempotent_and_preserves_reviews(self):
        self.assertEqual(load_demo(self.service, "demo")["loaded"], 6)
        fs = self.service.state()["findings"]
        self.service.review(fs[0]["id"], {"version": 1, "status": "confirmed", "comment": "Reviewed synthetic evidence."}, "examiner")
        self.assertEqual(load_demo(self.service, "demo")["loaded"], 0)
        self.assertEqual(self.service.finding(fs[0]["id"])["status"], "confirmed")

    def test_recommended_records_are_unique_cover_signals_and_explain_overlap(self):
        submission = self.ingest()
        assessment = self.service.assessment(submission["id"])
        selection = assessment["selection"]
        keys = [(record["kind"], record["record_id"]) for record in selection["records"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(selection["selected_count"], 8)
        self.assertEqual(set(selection["covered_detectors"]), {"fast_closure", "missing_escalation", "repeated_notes", "recurring_alerts", "closure_outlier", "sla_edge", "workflow_gap", "oversight_gap", "profile_outlier"})
        overlap = next(record for record in selection["records"] if len(record["signals"]) > 1)
        self.assertGreater(overlap["score_breakdown"]["additional_detectors"], 0)
        full = self.service.record(submission["id"], overlap["kind"], overlap["record_id"])
        self.assertTrue(full["timeline"])
        self.assertTrue(full["source"]["sha256"])
        self.assertEqual(len(full["signals"]), len(overlap["signals"]))
        self.assertTrue(all(signal["explanations"][0]["observed"] for signal in full["signals"]))
        self.assertEqual(selection, self.service.assessment(submission["id"])["selection"])

    def test_negative_space_record_contains_expected_coverage_and_missing_case(self):
        payload, labels = make_submission("coverage")
        submission = self.service.ingest(payload | {"entity_id": self.entity_id}, "examiner")
        asset = self.service.record(submission["id"], "assets", labels["coverage_gap"][0])
        self.assertEqual(asset["record"]["expected_monitoring"], "true")
        self.assertEqual(asset["linked_totals"]["coverage"], 0)
        self.assertIn("active coverage", next(f for f in asset["signals"] if f["detector"] == "coverage_gap")["explanations"][0]["expected"])
        alert = self.service.record(submission["id"], "alerts", labels["unlinked_case"][0])
        self.assertEqual(alert["missing_referenced_cases"], [alert["record"]["case_id"]])
        self.assertEqual(alert["linked_totals"]["cases"], 0)
        self.assertTrue(self.service.assessment(submission["id"])["submission"]["supervisory"]["negative_space"])

    def test_decisions_update_priority_and_remove_records_from_recommended_sample(self):
        submission = self.ingest()
        original_score = self.service.submission(submission["id"])["metrics"]["attention_score"]
        for finding in self.service.state()["findings"]:
            self.service.review(finding["id"], {"version": 1, "status": "dismissed", "comment": "Reviewed; approved procedure confirmed."}, "examiner")
        assessment = self.service.assessment(submission["id"])
        self.assertEqual(assessment["selection"]["selected_count"], 0)
        self.assertEqual(assessment["submission"]["supervisory"]["level"], "No open signals")
        self.assertEqual(assessment["submission"]["metrics"]["attention_score"], original_score)

    def test_historical_peer_benchmark_matches_period_and_retains_denominators(self):
        load_demo(self.service, "demo")
        state = self.service.state()
        atlas = next(s for s in state["submissions"] if "Atlas" in s["entity_name"] and s["period_start"].startswith("2026-08"))
        benchmark = atlas["peer_benchmark"]
        self.assertEqual(benchmark["cohort_size"], 2)
        self.assertTrue(all(peer["entity_id"] != atlas["entity_id"] for peer in benchmark["peers"]))
        self.assertTrue(all(metric["eligible_peers"] == 2 for metric in benchmark["metrics"]))
        self.assertIsNotNone(benchmark["metrics"][0]["peer_median"])

    def test_equal_file_percent_with_different_file_types_does_not_form_cohort(self):
        payload, _ = make_submission()
        payload["files"].pop("coverage")
        target = self.service.ingest(payload | {"entity_id": self.entity_id}, "examiner")
        for number in [1, 2]:
            peer = self.service.entity_create({"name": f"Peer {number}", "sector": "Energy", "size_band": "medium"}, "examiner")
            other, _ = make_submission("healthy", f"P{number}")
            other["files"].pop("assets")
            self.service.ingest(other | {"entity_id": peer["id"]}, "examiner")
        assessment = self.service.assessment(target["id"])
        self.assertEqual(assessment["submission"]["peer_benchmark"]["cohort_size"], 0)
        self.assertIsNone(assessment["submission"]["peer_benchmark"]["metrics"][0]["peer_median"])
        driver = next(d for d in assessment["submission"]["supervisory"]["drivers"] if d["id"] == "coverage_gap")
        self.assertFalse(driver["included_in_index"])
        self.assertEqual(driver["missing_inputs"], ["coverage"])

    def test_record_and_assessment_reject_unknown_identifiers(self):
        submission = self.ingest()
        for args in [(submission["id"], "cases", "missing"), (submission["id"], "unsupported", "missing")]:
            with self.assertRaises(ServiceError):
                self.service.record(*args)
        with self.assertRaises(ServiceError):
            self.service.assessment("missing")

    def test_investigation_has_computed_peer_evidence_and_input_presence(self):
        load_demo(self.service, 'demo')
        state = self.service.state()
        sub = next(s for s in state['submissions'] if 'Atlas' in s['entity_name'] and s['period_start'].startswith('2026-09'))
        f = next(f for f in state['findings'] if f['submission_id'] == sub['id'] and f['detector'] == 'missing_escalation')
        full = self.service.finding(f['id'], 0, 3)
        investigation = full['investigation']
        self.assertEqual(len(investigation['rows']), 3)
        self.assertTrue(all(r['escalation_count'] == 0 and r['severity'] == 'critical' for r in investigation['rows']))
        self.assertEqual(investigation['input_presence_percent'], 100)
        self.assertFalse(investigation['export_completeness_confirmed'])
        self.assertEqual(investigation['peer']['eligible_peers'], 2)
        self.assertIsNotNone(investigation['peer']['peer_median'])

    def test_independent_sample_excludes_case_alert_and_asset_flags(self):
        for profile, prefix in [('execution', 'ATL'), ('coverage', 'NOR')]:
            payload, _ = make_submission(profile, prefix)
            sub = self.service.ingest(payload | {'entity_id': self.entity_id}, 'examiner')['id']
            sample = self.service.sample(sub, count=1000)
            self.assertGreater(sample['excluded_cases'], 0)
            for case in sample['records']:
                record = self.service.record(sub, 'cases', case['case_id'])
                self.assertEqual(record['signals'], [])
                asset = self.service.record(sub, 'assets', case['asset_id'])
                self.assertEqual(asset['signals'], [])
            before = [r['case_id'] for r in sample['records']]
            for finding in [f for f in self.service.state()['findings'] if f['submission_id'] == sub]:
                self.service.review(finding['id'], {'version': 1, 'status': 'dismissed', 'comment': 'Synthetic export clarification.'}, 'examiner')
            self.assertEqual(before, [r['case_id'] for r in self.service.sample(sub, count=1000)['records']])

    def test_independent_observations_persist_audit_and_reject_stale_writes(self):
        sub = self.ingest()['id']
        original_score = self.service.submission(sub)['metrics']['attention_score']
        case = self.service.sample(sub)['records'][0]['case_id']
        data = {'case_id': case, 'status': 'concern', 'comment': 'Check external response documentation; possible missed concern.', 'version': 0}
        self.service.sample_observation(sub, data, 'examiner')
        restarted = Service(Store(self.path))
        self.assertEqual(restarted.sample(sub)['observations'][0]['case_id'], case)
        self.assertTrue(restarted.store.verify_audit()['valid'])
        with self.assertRaises(ServiceError) as conflict:
            restarted.sample_observation(sub, data, 'second')
        self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(restarted.submission(sub)['metrics']['attention_score'], original_score)
        report = restarted.report(submission_id=sub)
        self.assertIn(case, html_report(report))
        self.assertIn(data['comment'], html_report(report))
        bad = data | {'case_id': 'ATL-09-CASE-0006'}
        with self.assertRaises(ServiceError):
            restarted.sample_observation(sub, bad, 'examiner')

    def test_historical_engine_results_are_not_reinterpreted_as_new_rules(self):
        sub = self.ingest()['id']
        with self.service.store.transaction() as db:
            payload = json.loads(db.execute('SELECT payload FROM submissions WHERE id=?', (sub,)).fetchone()[0])
            payload['engine_version'] = '1.0.0'
            for key in ['closure_outlier', 'sla_edge']:
                payload['metrics']['measures'].pop(key)
                payload['metrics']['assessed'].pop(key)
            db.execute('UPDATE submissions SET payload=? WHERE id=?', (json.dumps(payload), sub))
        assessment = self.service.assessment(sub)
        for driver in [d for d in assessment['submission']['supervisory']['drivers'] if d['id'] in {'closure_outlier','sla_edge'}]:
            self.assertFalse(driver['included_in_index'])
            self.assertIn('Not implemented', driver['assessment_note'])

    def test_low_activity_is_directional_context_and_does_not_infer_coverage(self):
        load_demo(self.service, 'demo')
        sub = next(s for s in self.service.state()['submissions'] if 'Northstar' in s['entity_name'] and s['period_start'].startswith('2026-09'))
        context = self.service.assessment(sub['id'])['activity_context']
        self.assertTrue(context['attention'])
        self.assertLess(context['change_percent'], -70)
        self.assertIn('excluded from the attention index', context['limitation'])

    def test_peer_empty_populations_do_not_supply_zero_rates_or_comparable_index(self):
        target = self.ingest()
        for number in [1, 2]:
            peer = self.service.entity_create({"name": f"Empty peer {number}", "sector": "Energy", "size_band": "medium"}, "examiner")
            payload, _ = make_submission("healthy", f"E{number}")
            for kind in ["alerts", "cases", "escalations"]:
                payload["files"][kind]["content"] = payload["files"][kind]["content"].splitlines()[0] + "\n"
            self.service.ingest(payload | {"entity_id": peer["id"]}, "examiner")
        benchmark = self.service.assessment(target["id"])["submission"]["peer_benchmark"]
        fast = next(metric for metric in benchmark["metrics"] if metric["detector"] == "fast_closure")
        self.assertIsNone(fast["peer_median"])
        self.assertEqual(fast["eligible_peers"], 0)
        self.assertIsNone(benchmark["index_median"])
        coverage = next(metric for metric in benchmark["metrics"] if metric["detector"] == "coverage_gap")
        self.assertEqual(coverage["peer_median"], 0)


if __name__ == "__main__":
    unittest.main()
