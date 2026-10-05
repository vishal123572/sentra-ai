import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.demo import load_demo
from app.service import Service, csv_report, html_report
from app.storage import Store


class OfflineTests(unittest.TestCase):
    def test_assessment_review_and_report_with_all_socket_connections_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("socket.socket.connect", side_effect=AssertionError("Outbound connections disabled")), patch("socket.create_connection", side_effect=AssertionError("Network disabled")):
                service = Service(Store(Path(folder) / "offline.sqlite3"))
                load_demo(service, "offline-test")
                state = service.state()
                self.assertEqual(len(state["submissions"]), 6)
                finding = state["findings"][0]
                detail = service.finding(finding["id"])
                self.assertTrue(detail["evidence"]["records"])
                service.review(finding["id"], {"version": 1, "status": "clarification", "comment": "Offline examiner review completed."}, "examiner")
                report = service.report()
                self.assertTrue(report["audit"]["valid"])
                self.assertIn("Offline examiner review completed.", html_report(report))
                self.assertIn("clarification", csv_report(report))


if __name__ == "__main__":
    unittest.main()
