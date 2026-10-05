import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor
from app.server import Application, Handler
from app.demo import make_submission


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = Application(Path(cls.temp.name) / "test.sqlite3")
        with patch.dict(os.environ, {"SATSA_ADMIN_USER": "examiner", "SATSA_ADMIN_PASSWORD": "TestPassword123!"}):
            cls.app.bootstrap()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.app = cls.app
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def setUp(self):
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = ""

    def request(self, path, body=None, headers=None):
        h = dict(headers or {})
        if body is not None:
            h["Content-Type"] = "application/json"
            if self.csrf:
                h.setdefault("X-CSRF-Token", self.csrf)
        req = Request(self.origin + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
        try:
            response = self.client.open(req)
        except HTTPError as exc:
            response = exc
        raw = response.read()
        data = json.loads(raw) if response.headers.get("Content-Type", "").startswith("application/json") else raw.decode()
        return response.status, data, response.headers

    def login(self, username="examiner", password="TestPassword123!"):
        status, data, headers = self.request("/api/auth/login", {"username": username, "password": password})
        self.assertEqual(status, 200)
        self.csrf = data["csrf"]
        return headers

    def test_unauthenticated_data_is_protected_but_health_and_assets_work(self):
        self.assertEqual(self.request("/api/state")[0], 401)
        self.assertEqual(self.request("/api/health")[0], 200)
        status, page, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertRegex(page, r'src="/app\.js(?:\?v=[0-9.]+)?"')
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("/../app/server.py")[0], 404)

    def test_csrf_and_cross_origin_login_are_rejected(self):
        status, _, _ = self.request("/api/auth/login", {"username": "examiner", "password": "TestPassword123!"}, {"Origin": "https://unrelated.invalid"})
        self.assertEqual(status, 403)
        self.login()
        self.assertEqual(self.request("/api/entities", {"name": "CSRF test", "sector": "Energy"}, {"X-CSRF-Token": "incorrect"})[0], 403)

    def test_full_upload_review_report_and_logout(self):
        headers = self.login()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        status, entity, _ = self.request("/api/entities", {"name": "HTTP workflow", "sector": "Energy", "size_band": "medium"})
        self.assertEqual(status, 201)
        payload, _ = make_submission()
        payload["entity_id"] = entity["id"]
        self.assertTrue(self.request("/api/import/validate", payload)[1]["valid"])
        status, assessment, _ = self.request("/api/import/run", payload)
        self.assertEqual(status, 201)
        self.assertEqual(assessment["findings"], 9)
        state = self.request("/api/state")[1]
        finding = next(f for f in state["findings"] if f["entity_id"] == entity["id"])
        detail = self.request("/api/findings/"+finding["id"])[1]
        self.assertTrue(detail["evidence"]["records"])
        decision = {"version": detail["version"], "status": "clarification", "comment": "Verify completeness of the exported workflow."}
        self.assertEqual(self.request("/api/findings/"+finding["id"]+"/review", decision)[0], 200)
        self.assertEqual(self.request("/api/findings/"+finding["id"])[1]["status"], "clarification")
        for format in ["json", "csv", "html"]:
            status, report, headers = self.request("/api/report?entity_id="+entity["id"]+"&format="+format)
            self.assertEqual(status, 200)
            self.assertIn("attachment", headers["Content-Disposition"])
        self.assertTrue(self.request("/api/audit")[1]["verification"]["valid"])
        self.assertEqual(self.request("/api/auth/logout", {})[0], 200)
        self.assertEqual(self.request("/api/state")[0], 401)

    def test_reader_can_inspect_and_logout_but_cannot_mutate(self):
        self.login()
        self.assertEqual(self.request("/api/users", {"username": "readertest", "password": "ReaderPassword123!", "role": "reader"})[0], 201)
        self.request("/api/auth/logout", {})
        self.login("readertest", "ReaderPassword123!")
        self.assertEqual(self.request("/api/state")[0], 200)
        self.assertEqual(self.request("/api/entities", {"name": "Forbidden", "sector": "Energy"})[0], 403)
        self.assertEqual(self.request('/api/submissions/unknown/sample-observation', {'case_id': 'X', 'status': 'concern', 'comment': 'Read only attempt', 'version': 0})[0], 403)
        self.assertEqual(self.request("/api/auth/logout", {})[0], 200)

    def test_wrong_credentials_and_malformed_payloads(self):
        self.assertEqual(self.request("/api/auth/login", {"username": "examiner", "password": "bad"})[0], 401)
        self.login()
        self.assertEqual(self.request("/api/import/validate", {"files": {"alerts": None}, "period_start": "2026-09-01", "period_end": "2026-10-01"})[1]["valid"], False)
        self.assertEqual(self.request("/api/report?format=unknown")[0], 400)

    def test_assessment_record_drilldown_and_authentication(self):
        self.assertEqual(self.request("/api/submissions/missing/assessment")[0], 401)
        self.login()
        self.request("/api/demo/load", {})
        state = self.request("/api/state")[1]
        submission = next(s for s in state["submissions"] if "Northstar" in s["entity_name"] and s["period_start"].startswith("2026-09"))
        status, assessment, _ = self.request(f"/api/submissions/{submission['id']}/assessment")
        self.assertEqual(status, 200)
        self.assertEqual(assessment["selection"]["selected_count"], 8)
        asset = next(item for item in assessment["selection"]["records"] if item["kind"] == "assets")
        status, record, _ = self.request(f"/api/submissions/{submission['id']}/record?kind=assets&id={asset['record_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(record["linked_totals"]["coverage"], 0)
        self.assertTrue(record["signals"][0]["explanations"][0]["observed"])
        self.assertEqual(self.request(f"/api/submissions/{submission['id']}/record?kind=cases&id=missing")[0], 404)


if __name__ == "__main__":
    unittest.main()
