"""Vercel Python handler reusing the existing application and service routes."""
import os
import threading
from urllib.parse import parse_qs, urlsplit
from app.postgres import PostgresStore
from app.server import Application, Handler
from app.service import ServiceError

_application = None
_lock = threading.Lock()


class handler(Handler):
    @property
    def app(self):
        global _application
        if _application is None:
            with _lock:
                if _application is None:
                    url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
                    if not url:
                        raise ServiceError('Connect a Postgres database in Vercel Storage and set DATABASE_URL. Uploaded assessments require persistent storage.', 503)
                    if not os.getenv('SATSA_ADMIN_PASSWORD'):
                        raise ServiceError('Set SATSA_ADMIN_PASSWORD in the Vercel project environment, then redeploy.', 503)
                    os.environ['SATSA_SECURE_COOKIE'] = '1'
                    application = Application(store=PostgresStore(url))
                    application.bootstrap()
                    _application = application
        return _application

    def route(self, method):
        parsed = urlsplit(self.path)
        values = parse_qs(parsed.query)
        # Vercel rewrites pass the original API path explicitly. Preserve other
        # query parameters such as report format and evidence pagination.
        original = values.get('__satsa_path', [None])[0]
        if original:
            if not original.startswith('/api/') or '?' in original or '#' in original:
                raise ServiceError('Invalid API route.', 400)
            self.path = original + ('?' + parsed.query if parsed.query else '')
        return super().route(method)
