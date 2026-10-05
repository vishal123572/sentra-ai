"""Optional hosted persistence. The offline SQLite deployment has no dependencies."""
import contextlib
import sqlite3
from .storage import Store

# Schema mirrors SQLite so detector snapshots, source hashes and review history
# keep their existing structure. Writes serialize to protect the audit chain and
# optimistic review versions across separate Vercel function instances.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, sector TEXT NOT NULL, size_band TEXT NOT NULL, policy TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id), period_start TEXT NOT NULL, period_end TEXT NOT NULL, checksum TEXT NOT NULL, created_at TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, original_files TEXT NOT NULL, UNIQUE(entity_id,checksum));
CREATE INDEX IF NOT EXISTS idx_submissions_entity_period ON submissions(entity_id,period_end DESC,created_at DESC);
CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id), payload TEXT NOT NULL, status TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', reviewed_by TEXT, reviewed_at TEXT, version INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_findings_submission_status ON findings(submission_id,status);
CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, finding_id TEXT NOT NULL REFERENCES findings(id), status TEXT NOT NULL, comment TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_reviews_finding_time ON reviews(finding_id,created_at);
CREATE TABLE IF NOT EXISTS sample_observations(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id), case_id TEXT NOT NULL, status TEXT NOT NULL, comment TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL, version INTEGER NOT NULL, UNIQUE(submission_id,case_id,version));
CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id), label_sha256 TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(sequence BIGSERIAL PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
"""


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        value = self.cursor.fetchone()
        return Row(value) if value is not None else None

    def fetchall(self):
        return [Row(value) for value in self.cursor.fetchall()]

    def __iter__(self):
        return (Row(value) for value in self.cursor)


class Connection:
    def __init__(self, connection, integrity_error):
        self.connection, self.integrity_error = connection, integrity_error

    def execute(self, sql, params=()):
        try:
            # Application SQL uses parameter placeholders only outside literals.
            return Cursor(self.connection.execute(sql.replace('?', '%s'), params))
        except self.integrity_error as exc:
            raise sqlite3.IntegrityError('Database constraint violation') from exc


class PostgresStore(Store):
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row
        self._driver, self._row_factory, self._url = psycopg, dict_row, url
        self.path = 'Postgres (configured through DATABASE_URL)'
        with self.transaction() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    db.execute(statement)

    @contextlib.contextmanager
    def connect(self):
        with self._driver.connect(self._url, row_factory=self._row_factory,
                                  connect_timeout=10, prepare_threshold=None) as connection:
            yield Connection(connection, self._driver.IntegrityError)

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('SELECT pg_advisory_xact_lock(26157)')
            yield db
