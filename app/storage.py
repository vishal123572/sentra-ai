"""SQLite persistence and a tamper-evident (not tamper-proof) audit chain."""
import contextlib
import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240000).hex()
    return f"{salt}${hashed}"


def check_password(password, stored):
    salt, expected = stored.split("$", 1)
    return secrets.compare_digest(password_hash(password, salt).split("$", 1)[1], expected)


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, sector TEXT NOT NULL, size_band TEXT NOT NULL, policy TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id), period_start TEXT NOT NULL, period_end TEXT NOT NULL, checksum TEXT NOT NULL,
                created_at TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, original_files TEXT NOT NULL, UNIQUE(entity_id, checksum));
            CREATE INDEX IF NOT EXISTS idx_submissions_entity_period ON submissions(entity_id, period_end DESC, created_at DESC);
            CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id), payload TEXT NOT NULL,
                status TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', reviewed_by TEXT, reviewed_at TEXT, version INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS idx_findings_submission_status ON findings(submission_id, status);
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, finding_id TEXT NOT NULL REFERENCES findings(id), status TEXT NOT NULL, comment TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_reviews_finding_time ON reviews(finding_id, created_at);
            CREATE TABLE IF NOT EXISTS sample_observations(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id), case_id TEXT NOT NULL,
                status TEXT NOT NULL, comment TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL, version INTEGER NOT NULL,
                UNIQUE(submission_id,case_id,version));
            CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id), label_sha256 TEXT NOT NULL,
                actor TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(sequence INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
            PRAGMA optimize;
            """)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            # sqlite3.Connection's own context manager commits/rolls back, but
            # does not close. Close explicitly after every read or transaction.
            with db:
                yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def audit(db, actor, action, detail):
        previous = db.execute("SELECT hash FROM audit ORDER BY sequence DESC LIMIT 1").fetchone()
        previous = previous[0] if previous else "0" * 64
        ts, encoded = now(), dumps(detail)
        digest = hashlib.sha256(dumps([previous, ts, actor, action, encoded]).encode()).hexdigest()
        db.execute("INSERT INTO audit(created_at,actor,action,detail,previous_hash,hash) VALUES(?,?,?,?,?,?)", (ts, actor, action, encoded, previous, digest))

    def verify_audit(self):
        previous, count = "0" * 64, 0
        with self.connect() as db:
            for row in db.execute("SELECT * FROM audit ORDER BY sequence"):
                expected = hashlib.sha256(dumps([previous, row["created_at"], row["actor"], row["action"], row["detail"]]).encode()).hexdigest()
                if row["previous_hash"] != previous or row["hash"] != expected:
                    return {"valid": False, "checked": count, "first_invalid_sequence": row["sequence"]}
                previous, count = row["hash"], count + 1
        return {"valid": True, "checked": count, "head_hash": previous,
                "limitation": "Detects changes against the stored chain. A privileged database owner can rewrite the entire chain; external anchoring is needed for stronger assurance."}
