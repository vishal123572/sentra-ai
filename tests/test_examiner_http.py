"""Real HTTP workflow regressions. All records live in disposable databases."""
import csv
import hashlib
import io
import ipaddress
import json
import os
import socket
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from app.demo import make_submission
from app.server import Application, Handler


class Client:
    def __init__(self, origin):
        self.origin, self.csrf = origin, ''
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, path, body=None):
        headers = {'Content-Type': 'application/json', 'X-CSRF-Token': self.csrf}
        request = Request(self.origin + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            response = self.opener.open(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            mime = response.headers.get('Content-Type', '')
            value = json.loads(content) if mime.startswith('application/json') else content if mime.startswith('application/zip') else content.decode()
            return response.status, value

    def login(self, username='examiner'):
        code, data = self.request('/api/auth/login', {'username': username, 'password': 'SatSaDemo2026!'})
        if code == 200:
            self.csrf = data['csrf']
        return code, data


class ExaminerHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = Application(Path(cls.temp.name) / 'workflow.sqlite3')
        with patch.dict(os.environ, {'SATSA_ADMIN_USER': 'examiner', 'SATSA_ADMIN_PASSWORD': 'SatSaDemo2026!'}):
            cls.app.bootstrap()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.app = cls.app
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        self.client = Client(self.origin)
        self.assertEqual(self.client.login()[0], 200)

    def create_assessment(self, profile='execution'):
        code, entity = self.client.request('/api/entities', {'name': self.id().split('.')[-1], 'sector': 'Energy'})
        self.assertEqual(code, 201)
        payload, labels = make_submission(profile)
        payload['entity_id'] = entity['id']
        code, validation = self.client.request('/api/import/validate', payload)
        self.assertEqual(code, 200)
        self.assertTrue(validation['valid'])
        code, created = self.client.request('/api/import/run', payload)
        self.assertEqual(code, 201)
        code, assessment = self.client.request(f"/api/submissions/{created['id']}/assessment")
        self.assertEqual(code, 200)
        self.assertEqual(assessment['submission']['id'], created['id'])
        self.assertEqual(len(assessment['findings']), created['findings'])
        return created['id'], assessment, payload, labels

    def evidence_snapshot(self, submission):
        with self.app.store.connect() as db:
            row = db.execute('SELECT checksum,payload,original_files FROM submissions WHERE id=?', (submission,)).fetchone()
            findings = list(db.execute('SELECT id,payload FROM findings WHERE submission_id=? ORDER BY id', (submission,)))
            return tuple(row), [tuple(f) for f in findings]

    def test_decision_reasons_history_reports_and_immutable_evidence(self):
        submission, assessment, payload, _ = self.create_assessment()
        selected = assessment['selection']['records'][0]
        self.assertTrue(selected['selection_reason'])
        code, record = self.client.request(f"/api/submissions/{submission}/record?kind={selected['kind']}&id={selected['record_id']}")
        self.assertEqual(code, 200)
        self.assertTrue(record['timeline'])
        self.assertTrue(record['signals'][0]['explanations'])
        self.assertEqual(record['source']['sha256'], hashlib.sha256(payload['files'][selected['kind']]['content'].encode()).hexdigest())
        finding = record['signals'][0]['id']
        endpoint = f'/api/findings/{finding}/review'
        original = self.evidence_snapshot(submission)
        for status in ['confirmed', 'dismissed', 'clarification']:
            for reason in ['', '    ', 'tiny']:
                code, _ = self.client.request(endpoint, {'version': 1, 'status': status, 'comment': reason})
                self.assertEqual(code, 400)
        reasons = ['Accept after checking source records.', 'Dismiss after approved control evidence.', 'Need information about export completeness.']
        for version, (status, reason) in enumerate(zip(['confirmed', 'dismissed', 'clarification'], reasons), 1):
            self.assertEqual(self.client.request(endpoint, {'version': version, 'status': status, 'comment': reason})[0], 200)
        code, detail = self.client.request(f'/api/findings/{finding}')
        self.assertEqual(code, 200)
        self.assertEqual(detail['version'], 4)
        self.assertEqual({r['comment'] for r in detail['reviews']}, set(reasons))
        self.assertEqual(self.evidence_snapshot(submission), original)
        report = self.client.request(f'/api/report?submission_id={submission}')[1]
        reported = next(f for f in report['findings'] if f['id'] == finding)
        self.assertEqual({r['comment'] for r in reported['reviews']}, set(reasons))
        self.assertTrue(report['audit']['valid'])

    def test_simultaneous_review_and_observation_writes_have_one_winner(self):
        submission, assessment, _, _ = self.create_assessment()
        clients = [Client(self.origin), Client(self.origin)]
        for client in clients:
            self.assertEqual(client.login()[0], 200)
        finding = assessment['findings'][0]['id']
        sample = self.client.request(f'/api/submissions/{submission}/sample')[1]
        case = sample['records'][0]['case_id']
        endpoints = [(f'/api/findings/{finding}/review', {'version': 1, 'status': 'confirmed'}),
                     (f'/api/submissions/{submission}/sample-observation', {'version': 0, 'status': 'concern', 'case_id': case})]
        original = self.evidence_snapshot(submission)
        for endpoint, body in endpoints:
            barrier = threading.Barrier(2)
            def save(number):
                barrier.wait(timeout=5)
                return clients[number].request(endpoint, body | {'comment': f'Concurrent examiner evidence reason {number}.'})[0]
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(save, [0, 1]))
            self.assertEqual(sorted(results), [200, 409])
        detail = self.client.request(f'/api/findings/{finding}')[1]
        self.assertEqual((detail['version'], len(detail['reviews'])), (2, 1))
        observations = self.client.request(f'/api/submissions/{submission}/sample')[1]['observations']
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['version'], 1)
        self.assertEqual(self.evidence_snapshot(submission), original)
        self.assertTrue(self.client.request('/api/audit')[1]['verification']['valid'])

    def test_independent_observation_history_survives_restart_and_report(self):
        submission, assessment, _, _ = self.create_assessment('coverage')
        sample = self.client.request(f'/api/submissions/{submission}/sample')[1]
        case = sample['records'][0]['case_id']
        record = self.client.request(f'/api/submissions/{submission}/record?kind=cases&id={case}')[1]
        self.assertEqual(record['signals'], [])
        self.assertGreater(sample['excluded_cases'], 0)
        reasons = ['Concern needs independent source verification.', 'Source export checked; no concern remains.']
        for version, (status, reason) in enumerate(zip(['concern', 'no_concern'], reasons)):
            self.assertEqual(self.client.request(f'/api/submissions/{submission}/sample-observation',
                                                {'case_id': case, 'version': version, 'status': status, 'comment': reason})[0], 200)
        # Re-open the persisted file through a new application object.
        restarted = Application(Path(self.temp.name) / 'workflow.sqlite3')
        self.assertEqual({o['comment'] for o in restarted.service.sample(submission)['observations']}, set(reasons))
        report = self.client.request(f'/api/report?submission_id={submission}')[1]
        self.assertEqual(len(report['assessments'][0]['independent_sample']['observations']), 2)
        html = self.client.request(f'/api/report?submission_id={submission}&format=html')[1]
        for reason in reasons:
            self.assertIn(reason, html)
        self.assertEqual(restarted.service.submission(submission)['metrics'], assessment['submission']['metrics'])

    def test_reader_denied_every_mutating_route_and_examiner_denied_admin(self):
        submission, assessment, payload, _ = self.create_assessment()
        for username, role in [('flowreader', 'reader'), ('flowreviewer', 'examiner')]:
            self.assertEqual(self.client.request('/api/users', {'username': username, 'password': 'SatSaDemo2026!', 'role': role})[0], 201)
        reader = Client(self.origin)
        self.assertEqual(reader.login('flowreader')[0], 200)
        finding = assessment['findings'][0]['id']
        entity = payload['entity_id']
        routes = ['/api/entities', f'/api/entities/{entity}/policy', '/api/import/validate', '/api/import/run',
                  f'/api/findings/{finding}/review', f'/api/submissions/{submission}/sample-observation',
                  f'/api/submissions/{submission}/evaluate', f'/api/submissions/{submission}/reanalyse', '/api/demo/load', '/api/users']
        with self.app.store.connect() as db:
            audit_before = db.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        for endpoint in routes:
            self.assertEqual(reader.request(endpoint, {})[0], 403, endpoint)
        with self.app.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0], audit_before)
        for endpoint in [f'/api/submissions/{submission}/assessment', f'/api/findings/{finding}',
                         f'/api/report?submission_id={submission}', f'/api/submissions/{submission}/blind-review']:
            self.assertEqual(reader.request(endpoint)[0], 200)
        examiner = Client(self.origin)
        self.assertEqual(examiner.login('flowreviewer')[0], 200)
        for endpoint in ['/api/demo/load', '/api/users']:
            self.assertEqual(examiner.request(endpoint, {})[0], 403)
        self.assertEqual(reader.request('/api/auth/logout', {})[0], 200)
        self.assertEqual(reader.request('/api/state')[0], 401)

    def test_blinded_export_and_held_out_comparison_persist_hash_counts_yields(self):
        submission, assessment, _, labels = self.create_assessment()
        code, archive = self.client.request(f'/api/submissions/{submission}/blind-review')
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            records = json.loads(opened.read('records.json'))
            self.assertEqual(set(records), {'submission_id', 'period_start', 'period_end', 'datasets', 'policy'})
            blank_labels = list(csv.DictReader(io.StringIO(opened.read('labels.csv').decode())))
            self.assertTrue(all(row['expert_concern'] == '' and row['adjudicated'] == 'false' for row in blank_labels))
        clean = self.client.request(f'/api/submissions/{submission}/sample')[1]['records'][:2]
        positives = labels['fast_closure'][:2]
        # Artificial labels exercise the math only; they are not expert validation.
        truth = [(positives[0], True), (positives[1], False), (clean[0]['case_id'], True), (clean[1]['case_id'], False)]
        rows = [{'unit': 'cases', 'record_id': identifier, 'expert_concern': value, 'adjudicated': True, 'split': 'held_out'} for identifier, value in truth]
        rows += [rows[0] | {'adjudicated': False}, rows[0] | {'split': 'tuning'}]
        content = json.dumps(rows)
        code, comparison = self.client.request(f'/api/submissions/{submission}/evaluate', {'filename': 'synthetic-test-labels.json', 'content': content, 'budget': 2})
        self.assertEqual(code, 201)
        self.assertEqual(comparison['labelled_records'], 4)
        self.assertEqual(comparison['excluded_non_adjudicated_or_tuning'], 2)
        self.assertEqual(comparison['confusion'], dict(true_positive=1, false_positive=1, false_negative=1, true_negative=1))
        self.assertEqual((comparison['precision'], comparison['recall']), (.5, .5))
        self.assertEqual(comparison['label_sha256'], hashlib.sha256(content.encode()).hexdigest())
        truth_map = dict(truth)
        for key in ['prioritised_review', 'hash_baseline_review']:
            result = comparison[key]
            self.assertLessEqual(result['reviewed'], 2)
            self.assertEqual(result['reviewed'], len(result['record_ids']))
            self.assertEqual(result['concerns_found'], sum(truth_map[row['record_id']] for row in result['record_ids']))
        report = self.client.request(f'/api/report?submission_id={submission}')[1]
        self.assertEqual(report['expert_comparisons'][0], comparison)
        html = self.client.request(f'/api/report?submission_id={submission}&format=html')[1]
        self.assertIn(comparison['label_sha256'], html)
        audit = self.client.request('/api/audit')[1]
        self.assertTrue(audit['verification']['valid'])
        self.assertTrue(any(event['action'] == 'expert_comparison.created' and event['detail']['label_sha256'] == comparison['label_sha256'] for event in audit['records']))

    def test_expired_session_cannot_read_or_write(self):
        client = Client(self.origin)
        self.assertEqual(client.login()[0], 200)
        with self.app.store.transaction() as db:
            db.execute('UPDATE sessions SET expires=0 WHERE csrf=?', (client.csrf,))
        self.assertEqual(client.request('/api/state')[0], 401)
        self.assertEqual(client.request('/api/entities', {'name': 'Expired user mutation', 'sector': 'Energy'})[0], 401)

    def test_http_import_investigation_review_and_report_with_outbound_sockets_blocked(self):
        original_connect, original_create = socket.socket.connect, socket.create_connection

        def check(address):
            if not isinstance(address, tuple) or not ipaddress.ip_address(address[0]).is_loopback:
                raise AssertionError(f'Outbound connection blocked: {address}')

        def connect(sock, address):
            check(address)
            return original_connect(sock, address)

        def create(address, *args, **kwargs):
            check(address)
            return original_create(address, *args, **kwargs)

        with patch('socket.socket.connect', connect), patch('socket.create_connection', create):
            for asset in ['/', '/app.js', '/styles.css']:
                self.assertEqual(self.client.request(asset)[0], 200)
            submission, assessment, _, _ = self.create_assessment()
            finding = assessment['findings'][0]['id']
            detail = self.client.request(f'/api/findings/{finding}')[1]
            self.assertTrue(detail['evidence']['records'])
            self.assertEqual(self.client.request(f'/api/findings/{finding}/review',
                                                {'version': 1, 'status': 'clarification', 'comment': 'Offline HTTP examiner verification.'})[0], 200)
            for format in ['json', 'html', 'csv']:
                self.assertEqual(self.client.request(f'/api/report?submission_id={submission}&format={format}')[0], 200)
            self.assertEqual(self.client.request(f'/api/submissions/{submission}/blind-review')[0], 200)
            self.assertTrue(self.client.request('/api/audit')[1]['verification']['valid'])
