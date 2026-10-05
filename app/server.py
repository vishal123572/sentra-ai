"""Local HTTP application. Python 3.10+ standard library; no network dependencies."""
import argparse
import hashlib
import json
import logging
import mimetypes
import os
import secrets
import socket
import time
from collections import defaultdict, deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .analytics import SCHEMAS, ENGINE_VERSION
from .version import APPLICATION_VERSION
from .service import Service, ServiceError, csv_report, html_report
from .storage import Store, check_password, dumps, now, password_hash

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 4 * 1024 * 1024 if os.getenv('VERCEL') else 24 * 1024 * 1024
DEFAULT_DEMO_PASSWORD = "SatSaDemo2026!"


class LocalHTTPServer(ThreadingHTTPServer):
    """Windows must reject a second listener instead of sharing the same port."""
    allow_reuse_address = os.name != 'nt'
    daemon_threads = True

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Application:
    def __init__(self, database=None, *, store=None):
        self.store = store if store is not None else Store(database)
        self.service = Service(self.store)
        self.failures = defaultdict(deque)

    def bootstrap(self):
        with self.store.transaction() as db:
            if db.execute("SELECT id FROM users LIMIT 1").fetchone():
                return None
            username = os.getenv("SATSA_ADMIN_USER", "examiner")
            if os.getenv('VERCEL') and not os.getenv('SATSA_ADMIN_PASSWORD'):
                raise ServiceError('Set SATSA_ADMIN_PASSWORD in the Vercel project before creating the first account.', 503)
            password = os.getenv("SATSA_ADMIN_PASSWORD") or DEFAULT_DEMO_PASSWORD
            if len(password) < 10:
                raise ValueError("SATSA_ADMIN_PASSWORD must contain at least 10 characters.")
            db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (secrets.token_hex(8), username, password_hash(password), "admin", now()))
            Store.audit(db, "system", "account.bootstrap", {"username": username})
        return username, password

    def login(self, username, password, ip):
        failures = self.failures[ip]
        while failures and failures[0] < time.time() - 60:
            failures.popleft()
        if len(failures) >= 6:
            raise ServiceError("Too many unsuccessful attempts. Try again in one minute.", 429)
        with self.store.transaction() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            stored = user["password"] if user else password_hash("invalid-placeholder", "0" * 32)
            if not check_password(password, stored) or not user:
                failures.append(time.time())
                raise ServiceError("Incorrect username or password.", 401)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, time.time() + 8 * 3600))
            Store.audit(db, user["username"], "session.login", {})
        return {"username": user["username"], "role": user["role"], "csrf": csrf}, token

    def session(self, cookie):
        try:
            parsed = SimpleCookie(cookie or "")
            token = parsed["satsa_session"].value
        except Exception:
            return None
        with self.store.connect() as db:
            row = db.execute("SELECT u.username,u.role,s.csrf,s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(row) if row else None


class Handler(BaseHTTPRequestHandler):
    server_version = "SATSA/" + APPLICATION_VERSION

    def log_message(self, fmt, *args):
        # Don't log query strings or request bodies, which may contain evidence.
        logging.info("%s %s %s", self.client_address[0], self.command, urlsplit(self.path).path)

    @property
    def app(self):
        return self.server.app

    def respond(self, value, status=200, mime="application/json; charset=utf-8", extra=None):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        body = value if isinstance(value, bytes) else str(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ServiceError("Invalid content length.", 400)
        if length > MAX_BODY or length < 0:
            self.close_connection = True
            raise ServiceError(f"Upload limit is {MAX_BODY // (1024 * 1024)} MiB per request in this deployment. Split exports into smaller assessment bundles.", 413)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ServiceError("Send application/json.", 415)
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise ServiceError("Invalid JSON body.")
        if not isinstance(data, dict):
            raise ServiceError("Request body must be an object.")
        return data

    def require_user(self, mutation=False, admin=False, allow_reader=False):
        user = self.app.session(self.headers.get("Cookie"))
        if not user:
            raise ServiceError("Please sign in.", 401)
        if mutation:
            csrf = self.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(csrf, user["csrf"]):
                raise ServiceError("Session verification failed. Reload and try again.", 403)
            if user["role"] == "reader" and not allow_reader:
                raise ServiceError("Read-only accounts cannot change assessments.", 403)
        if admin and user["role"] != "admin":
            raise ServiceError("Administrator access required.", 403)
        return user

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            self.route(method)
        except ServiceError as exc:
            self.respond({"error": exc.message, "details": exc.details}, exc.status)
        except (ValueError, TypeError) as exc:
            self.respond({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception("Request failed")
            self.respond({"error": "Unable to process the request. Check the application logs."}, 500)

    def route(self, method):
        parsed = urlsplit(self.path)
        path, query = parsed.path.rstrip("/") or "/", parse_qs(parsed.query)
        parts = path.strip("/").split("/")
        if path == "/api/health" and method == "GET":
            return self.respond({"status": "ok", "version": APPLICATION_VERSION, "engine_version": ENGINE_VERSION, "mode": "hosted" if os.getenv('VERCEL') else "offline", "max_body_bytes": MAX_BODY})
        if path == "/api/auth/login" and method == "POST":
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                raise ServiceError("Cross-origin sign-in is not allowed.", 403)
            data = self.json_body()
            username, password = data.get("username", ""), data.get("password", "")
            if not isinstance(username, str) or not isinstance(password, str) or len(password) > 512 or len(username) > 100:
                raise ServiceError("Invalid credentials.")
            user, token = self.app.login(username, password, self.client_address[0])
            secure = "; Secure" if os.getenv("SATSA_SECURE_COOKIE") == "1" else ""
            return self.respond(user, extra={"Set-Cookie": f"satsa_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}"})
        if path == "/api/auth/me" and method == "GET":
            user = self.require_user()
            return self.respond({k: user[k] for k in ["username", "role", "csrf"]})
        if path.startswith("/api/"):
            user = self.require_user(mutation=method != "GET", allow_reader=path == "/api/auth/logout")
            service = self.app.service
            if method == "GET":
                if path == '/api/runtime':
                    self.require_user(admin=True)
                    return self.respond({'application_version': APPLICATION_VERSION, 'engine_version': ENGINE_VERSION,
                                         'source_directory': str(ROOT), 'database': str(Path(self.app.store.path).resolve()), 'pid': os.getpid()})
                if path == "/api/state":
                    return self.respond(service.state())
                if path == "/api/audit":
                    with self.app.store.connect() as db:
                        rows = [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY sequence DESC LIMIT 200")]
                    for row in rows:
                        row["detail"] = json.loads(row["detail"])
                    return self.respond({"verification": self.app.store.verify_audit(), "records": rows})
                if len(parts) == 3 and parts[1] == "findings":
                    offset = max(0, int(query.get("offset", [0])[0]))
                    limit = min(100, max(1, int(query.get("limit", [25])[0])))
                    return self.respond(service.finding(parts[2], offset, limit))
                if len(parts) == 3 and parts[1] == "submissions":
                    return self.respond(service.submission(parts[2]))
                if len(parts) == 4 and parts[1] == "submissions" and parts[3] == "sample":
                    return self.respond(service.sample(parts[2]))
                if len(parts) == 4 and parts[1] == 'submissions' and parts[3] == 'blind-review':
                    return self.respond(service.blind_review(parts[2]), mime='application/zip', extra={'Content-Disposition': 'attachment; filename="SENTRA-AI-blinded-review.zip"'})
                if len(parts) == 4 and parts[1] == "submissions" and parts[3] == "assessment":
                    return self.respond(service.assessment(parts[2]))
                if len(parts) == 4 and parts[1] == "submissions" and parts[3] == "record":
                    return self.respond(service.record(parts[2], query.get("kind", [""])[0], query.get("id", [""])[0]))
                if path == "/api/report":
                    report = service.report(query.get("entity_id", [None])[0], query.get("submission_id", [None])[0])
                    format = query.get("format", ["json"])[0]
                    mime, body, ext = "application/json; charset=utf-8", report, "json"
                    if format == "csv":
                        mime, body, ext = "text/csv; charset=utf-8", csv_report(report), "csv"
                    elif format == "html":
                        mime, body, ext = "text/html; charset=utf-8", html_report(report), "html"
                    elif format != "json":
                        raise ServiceError("Choose json, csv or html.")
                    return self.respond(body, mime=mime, extra={"Content-Disposition": f'attachment; filename="SENTRA-AI-assessment.{ext}"'})
                if len(parts) == 3 and parts[1] == "templates":
                    kind = parts[2].replace(".csv", "")
                    if kind not in SCHEMAS:
                        raise ServiceError("Template not found.", 404)
                    text = ",".join(SCHEMAS[kind]["required"] + SCHEMAS[kind]["optional"]) + "\n"
                    return self.respond(text, mime="text/csv; charset=utf-8", extra={"Content-Disposition": f'attachment; filename="{kind}.csv"'})
            else:
                data = self.json_body()
                if path == "/api/auth/logout":
                    with self.app.store.transaction() as db:
                        db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
                        Store.audit(db, user["username"], "session.logout", {})
                    return self.respond({"signed_out": True}, extra={"Set-Cookie": "satsa_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
                if path == "/api/entities":
                    return self.respond(service.entity_create(data, user["username"]), 201)
                if len(parts) == 4 and parts[1] == "entities" and parts[3] == "policy":
                    return self.respond(service.entity_policy(parts[2], data, user["username"]))
                if path == "/api/import/validate":
                    return self.respond(service.validate(data))
                if path == "/api/import/run":
                    return self.respond(service.ingest(data, user["username"]), 201)
                if len(parts) == 4 and parts[1] == "findings" and parts[3] == "review":
                    return self.respond(service.review(parts[2], data, user["username"]))
                if len(parts) == 4 and parts[1] == "submissions" and parts[3] == "sample-observation":
                    return self.respond(service.sample_observation(parts[2], data, user["username"]))
                if len(parts) == 4 and parts[1] == 'submissions' and parts[3] == 'evaluate':
                    return self.respond(service.evaluate(parts[2], data, user['username']), 201)
                if len(parts) == 4 and parts[1] == 'submissions' and parts[3] == 'reanalyse':
                    return self.respond(service.reanalyse(parts[2], data, user['username']), 201)
                if path == "/api/demo/load":
                    self.require_user(mutation=True, admin=True)
                    from .demo import load_demo
                    return self.respond(load_demo(service, user["username"]))
                if path == "/api/users":
                    self.require_user(mutation=True, admin=True)
                    username, password, role = str(data.get("username", "")).strip(), data.get("password", ""), data.get("role", "reader")
                    if not 3 <= len(username) <= 60 or not isinstance(password, str) or not 10 <= len(password) <= 512 or role not in {"examiner", "reader"}:
                        raise ServiceError("Use a username of 3–60 characters, a password of 10–512 characters, and an examiner/reader role.")
                    with self.app.store.transaction() as db:
                        if db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                            raise ServiceError("Username already exists.", 409)
                        db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (secrets.token_hex(8), username, password_hash(password), role, now()))
                        Store.audit(db, user["username"], "account.created", {"username": username, "role": role})
                    return self.respond({"created": True}, 201)
            raise ServiceError("API route not found.", 404)
        if method != "GET":
            raise ServiceError("Route not found.", 404)
        web = ROOT / "web"
        file = (web / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not file.is_relative_to(web.resolve()) or not file.is_file():
            raise ServiceError("File not found.", 404)
        mime = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if mime.startswith("text/") or mime == "application/javascript":
            mime += "; charset=utf-8"
        return self.respond(file.read_bytes(), mime=mime)


def main():
    parser = argparse.ArgumentParser(description="SAT-SA offline supervisory assessment workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--database", default=str(ROOT / "data" / "satsa.sqlite3"))
    parser.add_argument("--demo", action="store_true", help="Load clearly labelled synthetic demonstration entities.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Bind before opening or migrating any database, bootstrapping or seeding.
    # A failed launch must not create data while a different release owns the URL.
    try:
        server = LocalHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        parser.exit(1, f'Cannot bind {args.host}:{args.port}: {exc}\nAnother SAT-SA process may already be serving this address. Stop the old process or select --port. No database was opened.\nRequested application {APPLICATION_VERSION}, engine {ENGINE_VERSION}\nSource: {ROOT}\nDatabase: {Path(args.database).resolve()}\n')
    app = Application(args.database)
    credentials = app.bootstrap()
    if args.demo:
        from .demo import load_demo
        load_demo(app.service, "system")
    server.app = app
    server.daemon_threads = True
    print(f"\nSAT-SA is ready: http://{args.host}:{args.port}")
    print(f"Application {APPLICATION_VERSION} / running engine {ENGINE_VERSION} / PID {os.getpid()}")
    print(f"Source: {ROOT}\nDatabase: {Path(args.database).resolve()}")
    if credentials:
        print(f"First-run account: {credentials[0]}\nPassword: {credentials[1]}")
    else:
        print("Sign in with your existing local account. Default demo login: examiner / SatSaDemo2026!")
        print("For an older database, run: python manage.py reset-demo-password")
    print("All processing is local. Press Ctrl+C to stop.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SAT-SA.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
