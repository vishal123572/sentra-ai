"""Persistence regression checks using disposable databases only."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.storage import Store


class StorageTests(unittest.TestCase):
    def test_connections_close_and_transactions_commit_or_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'storage.sqlite3')
            with store.connect() as connection:
                self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
            with store.transaction() as connection:
                Store.audit(connection, 'test', 'committed', {'value': 1})
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
            with self.assertRaisesRegex(RuntimeError, 'rollback requested'):
                with store.transaction() as failed:
                    Store.audit(failed, 'test', 'rolled_back', {'value': 2})
                    raise RuntimeError('rollback requested')
            with self.assertRaises(sqlite3.ProgrammingError):
                failed.execute('SELECT 1')
            with store.connect() as connection:
                self.assertEqual([r['action'] for r in connection.execute('SELECT action FROM audit')], ['committed'])
            self.assertTrue(store.verify_audit()['valid'])
