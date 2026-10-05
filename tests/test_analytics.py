import copy
import json
import unittest
from app.analytics import analyse, DEFAULT_POLICY, parse_file, validate_policy, validate_submission
from app.demo import make_submission


class AnalyticsTests(unittest.TestCase):
    def assess(self, payload):
        result = validate_submission(payload["files"], payload["period_start"], payload["period_end"])
        self.assertTrue(result["valid"], result["issues"])
        return analyse(result["datasets"], DEFAULT_POLICY, payload["period_start"], payload["period_end"])

    def test_planted_execution_signals_and_legitimate_automation(self):
        payload, labels = make_submission("execution")
        result = self.assess(payload)
        findings = {f["detector"]: f for f in result["findings"]}
        for key in ["fast_closure", "missing_escalation", "repeated_notes", "closure_outlier", "sla_edge", "recurring_alerts"]:
            self.assertEqual(set(findings[key]["evidence_ids"]), set(labels[key]))
        self.assertEqual(findings["recurring_alerts"]["affected_count"], 10)
        self.assertNotIn("coverage_gap", findings)

    def test_healthy_case_has_no_signal_despite_automated_fast_closures(self):
        payload, _ = make_submission("healthy")
        result = self.assess(payload)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["metrics"]["attention_score"], 0)

    def test_planted_coverage_and_missing_case_evidence(self):
        payload, labels = make_submission("coverage")
        result = self.assess(payload)
        findings = {f["detector"]: f for f in result["findings"]}
        for key in ["coverage_gap", "unlinked_case", "missing_escalation"]:
            self.assertEqual(set(findings[key]["evidence_ids"]), set(labels[key]))

    def test_missing_files_are_unassessed_not_negative_findings(self):
        payload, _ = make_submission("coverage")
        payload["files"] = {"alerts": payload["files"]["alerts"]}
        result = self.assess(payload)
        self.assertEqual(result["findings"], [])
        self.assertIsNone(result["metrics"]["attention_score"])
        self.assertFalse(result["metrics"]["assessed"]["coverage_gap"])
        self.assertFalse(result["metrics"]["assessed"]["missing_escalation"])

    def test_zero_alerts_do_not_imply_missing_coverage(self):
        payload, _ = make_submission("healthy")
        payload["files"]["alerts"]["content"] = payload["files"]["alerts"]["content"].splitlines()[0] + "\n"
        result = self.assess(payload)
        self.assertNotIn("coverage_gap", [f["detector"] for f in result["findings"]])

    def test_bad_timeline_blocks_assessment(self):
        payload, _ = make_submission("healthy")
        rows, _ = parse_file("cases", payload["files"]["cases"])
        rows[0]["closed_at"] = "2026-08-01T00:00:00Z"
        payload["files"]["cases"] = {"format": "json", "content": json.dumps(rows)}
        result = validate_submission(payload["files"], payload["period_start"], payload["period_end"])
        self.assertFalse(result["valid"])
        self.assertTrue(any("precedes" in i["message"] for i in result["issues"]))

    def test_duplicate_ids_and_invalid_boolean_block_validation(self):
        payload, _ = make_submission("healthy")
        rows, _ = parse_file("assets", payload["files"]["assets"])
        rows[1]["asset_id"] = rows[0]["asset_id"]
        rows[1]["expected_monitoring"] = "maybe"
        payload["files"]["assets"] = {"format": "json", "content": json.dumps(rows)}
        result = validate_submission(payload["files"], payload["period_start"], payload["period_end"])
        self.assertFalse(result["valid"])
        self.assertTrue(any("Duplicate" in i["message"] for i in result["issues"]))
        self.assertTrue(any("true or false" in i["message"] for i in result["issues"]))

    def test_source_column_mapping_and_json(self):
        rows, _ = parse_file("alerts", {"format": "json", "content": json.dumps([{"ID": "A1", "Host": "X1", "Type": "Login", "Level": "high", "Time": "2026-09-01T12:00:00Z"}]),
                                      "mapping": {"alert_id": "ID", "asset_id": "Host", "category": "Type", "severity": "Level", "created_at": "Time"}})
        self.assertEqual(rows[0]["alert_id"], "A1")

    def test_period_end_is_exclusive(self):
        payload, _ = make_submission("healthy")
        rows, _ = parse_file("alerts", payload["files"]["alerts"])
        rows[0]["created_at"] = payload["period_end"]
        rows[0]["acknowledged_at"] = payload["period_end"]
        payload["files"]["alerts"] = {"format": "json", "content": json.dumps(rows)}
        result = self.assess(payload)
        self.assertEqual(result["metrics"]["alerts"], 159)

    def test_stale_coverage_and_future_coverage_are_not_valid_at_period_end(self):
        payload, _ = make_submission("healthy")
        rows, _ = parse_file("coverage", payload["files"]["coverage"])
        rows[0]["last_seen_at"] = "2026-09-01T00:00:00Z"
        rows[1]["last_seen_at"] = "2026-10-03T00:00:00Z"
        payload["files"]["coverage"] = {"format": "json", "content": json.dumps(rows)}
        result = self.assess(payload)
        finding = next(f for f in result["findings"] if f["detector"] == "coverage_gap")
        self.assertEqual(finding["affected_count"], 2)

    def test_invalid_policy_is_rejected(self):
        for patch in [{"fast_closure_minutes": 0}, {"repeated_alert_minimum": 2.5}, {"escalation_severities": ["urgent"]}]:
            with self.assertRaises(ValueError):
                validate_policy(patch)

    def test_distribution_outlier_beyond_fixed_fast_closure_threshold(self):
        payload, _ = make_submission()
        finding = next(f for f in self.assess(payload)['findings'] if f['detector'] == 'closure_outlier')
        self.assertIn('ATL-09-CASE-0111', finding['evidence_ids'])
        self.assertGreater(finding['context']['lower_fence_minutes'], 7)
        fast = next(f for f in self.assess(payload)['findings'] if f['detector'] == 'fast_closure')
        self.assertNotIn('ATL-09-CASE-0111', fast['evidence_ids'])

    def test_sla_cluster_with_good_investigation_does_not_flag(self):
        payload, _ = make_submission('healthy')
        rows, _ = parse_file('alerts', payload['files']['alerts'])
        from datetime import timedelta
        from app.analytics import timestamp
        for row in rows:
            row['acknowledged_at'] = (timestamp(row['created_at']) + timedelta(minutes=29.5)).isoformat()
        payload['files']['alerts'] = {'format': 'json', 'content': json.dumps(rows)}
        self.assertNotIn('sla_edge', [f['detector'] for f in self.assess(payload)['findings']])

    def test_manual_only_semantic_concern_remains_available_for_independent_review(self):
        payload, _ = make_submission('healthy')
        result = self.assess(payload)
        self.assertEqual(result['findings'], [])
        rows, _ = parse_file('cases', payload['files']['cases'])
        case = next(c for c in rows if c['case_id'] == 'ATL-09-CASE-0021')
        self.assertIn('restore test is still failing', case['investigation_notes'])

    def test_small_baselines_remain_unassessed(self):
        payload, _ = make_submission('healthy', rows=10)
        result = self.assess(payload)
        self.assertFalse(result['metrics']['assessed']['closure_outlier'])
        self.assertFalse(result['metrics']['assessed']['sla_edge'])
        self.assertNotIn('closure_outlier', [f['detector'] for f in result['findings']])
        self.assertNotIn('sla_edge', [f['detector'] for f in result['findings']])


if __name__ == "__main__":
    unittest.main()
