#!/usr/bin/env python3
"""Run reproducible validation and a bounded synthetic performance measurement."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from datetime import datetime, timezone
from pathlib import Path
from app.demo import load_demo, make_submission
from app.service import Service
from app.storage import Store


def main():
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    with tempfile.TemporaryDirectory() as folder:
        service = Service(Store(Path(folder) / "validation.sqlite3"))
        entity = service.entity_create({"name": "Synthetic performance fixture", "sector": "Energy", "size_band": "medium"}, "validation")
        payload, _ = make_submission("execution", "BENCH", rows=10000)
        encoded_bytes = len(json.dumps(payload).encode())
        tracemalloc.start()
        started = time.perf_counter()
        outcome = service.ingest(payload | {"entity_id": entity["id"]}, "validation")
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        bench = {"alerts": 10000, "cases": 10000, "total_source_records": outcome["rows"], "payload_bytes": encoded_bytes,
                 "ingest_and_analyse_seconds_with_tracemalloc": round(elapsed, 3), "peak_python_allocations_mib": round(peak / 1024 / 1024, 2),
                 "findings": outcome["findings"], "limitation": "Single synthetic in-process import with allocation tracing. Not HTTP load, browser, RSS or production-capacity certification."}
        demo_service = Service(Store(Path(folder) / "demo.sqlite3"))
        load_demo(demo_service, "validation")
        fixture = Path(folder) / "frontend.json"
        state = demo_service.state()
        atlas = next(s for s in state["submissions"] if "Atlas Grid" in s["entity_name"] and s["period_start"].startswith("2026-09"))
        assessment = demo_service.assessment(atlas["id"])
        selected = assessment["selection"]["records"][0]
        record = demo_service.record(atlas["id"], selected["kind"], selected["record_id"])
        finding = demo_service.finding(record["signals"][0]["id"])
        fixture.write_text(json.dumps({"state": state, "assessment": assessment, "record": record, "finding": finding}), encoding="utf-8")
        frontend = {"status": "not_run", "limitation": "No browser automation: checks rendering functions and escaping only."}
        import shutil
        if shutil.which("node"):
            check = subprocess.run(["node", "tests/test_frontend.js", str(fixture)], capture_output=True, text=True)
            frontend.update({"status": "passed" if check.returncode == 0 else "failed", "output": check.stdout + check.stderr})
            if check.returncode:
                raise SystemExit(check.stderr or check.stdout)
            import urllib.request
            workflow_input = Path(folder) / "workflow-import.json"
            workflow_input.write_text(json.dumps(make_submission()[0]), encoding="utf-8")
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            environment = os.environ | {"SATSA_ADMIN_USER": "examiner", "SATSA_ADMIN_PASSWORD": "SatSaDemo2026!"}
            server = subprocess.Popen([sys.executable, "run.py", "--demo", "--port", str(port), "--database", str(Path(folder) / "workflow.sqlite3")],
                                      env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for attempt in range(60):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.05)
                workflow = subprocess.run(["node", "tests/test_workflow.js", f"http://127.0.0.1:{port}", str(workflow_input)], capture_output=True, text=True)
                frontend["http_action_workflow"] = {"status": "passed" if workflow.returncode == 0 else "failed", "output": workflow.stdout + workflow.stderr,
                                                   "limitation": "Actual frontend handlers and HTTP server; DOM is stubbed, so not a browser/layout check."}
                if workflow.returncode:
                    raise SystemExit(workflow.stdout + workflow.stderr)
            finally:
                server.terminate()
                server.wait(timeout=5)
        validation = {"generated_at": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
                      "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                      "offline_workflow": "passed with socket connections blocked", "frontend_render_checks": frontend,
                      "performance": bench, "not_validated": ["Browser interactions and visual layout", "Docker execution", "Real SOC expert-labelled efficacy", "Production security/load readiness"]}
        output = Path("docs/validation-results.json")
        output.write_text(json.dumps(validation, indent=2), encoding="utf-8")
        print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
