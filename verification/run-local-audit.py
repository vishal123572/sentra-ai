"""Disposable local audit; never uses the existing user database or cloud data."""
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from app.demo import load_demo, make_submission
from app.server import Application, Handler, LocalHTTPServer
from app.storage import dumps

root = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with tempfile.TemporaryDirectory(prefix='sentra-sih-audit-') as folder:
    app = Application(Path(folder) / 'audit.sqlite3')
    app.bootstrap()
    load_demo(app.service, 'audit-synthetic')
    state = app.service.state()
    target = next(s for s in state['submissions'] if 'Atlas Grid' in s['entity_name'] and s['period_start'].startswith('2026-09'))
    assessment = app.service.assessment(target['id'])
    selected = assessment['selection']['records'][0]
    fixture = {'state': state, 'assessment': assessment,
               'record': app.service.record(target['id'], selected['kind'], selected['record_id']),
               'finding': app.service.finding(assessment['findings'][0]['id'])}
    render_path = Path(folder) / 'render.json'
    render_path.write_text(dumps(fixture), encoding='utf-8')
    payload, _ = make_submission('execution')
    payload_path = Path(folder) / 'payload.json'
    payload_path.write_text(dumps(payload), encoding='utf-8')
    server = LocalHTTPServer(('127.0.0.1', 0), Handler)
    server.app = app
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    results = []
    try:
        for command in [['node', 'tests/test_frontend.js', str(render_path)],
                        ['node', 'tests/test_workflow.js', origin, str(payload_path)]]:
            result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=90, encoding='utf-8')
            print(result.stdout, end='')
            if result.stderr:
                print(result.stderr)
            results.append({'command': command[:2], 'exit_code': result.returncode,
                            'stdout': result.stdout, 'stderr': result.stderr})
        (root / 'verification' / 'local-frontend-audit.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    raise SystemExit(any(result['exit_code'] for result in results))
