#!/usr/bin/env python3
"""Convert periodic exports into an offline SAT-SA bundle; never collect continuously."""
import argparse
from contextlib import closing
import ipaddress
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.analytics import SCHEMAS, validate_submission


def sqlite_snapshot(path, tables=None):
    """Read only an exported SQLite database with explicit safe table names."""
    tables = tables or {kind: kind for kind in SCHEMAS}
    data = {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        available = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for kind, table in tables.items():
            if kind not in SCHEMAS or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', table):
                raise ValueError('Use supported dataset keys and simple table identifiers.')
            if table not in available:
                continue
            rows = [dict(r) for r in db.execute(f'SELECT * FROM "{table}" LIMIT 100001')]
            if len(rows) > 100000:
                raise ValueError('Export exceeds 100,000 rows per table; split submissions.')
            data[kind] = rows
    return data


def api_snapshot(url):
    """One explicit local/internal request; never call an Internet endpoint."""
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password:
        raise ValueError('Use a local HTTP(S) URL without embedded credentials.')
    if parsed.hostname != 'localhost':
        try:
            host = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            raise ValueError('Use localhost or an explicit private IP address.') from None
        if not (host.is_loopback or host.is_private) or host.is_link_local or host.is_unspecified or host.is_multicast:
            raise ValueError('Only loopback or private-network endpoints are permitted.')
    headers = {'Accept': 'application/json'}
    token = os.getenv('SATSA_IMPORT_API_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer '+token
    # Disallow redirects so a local endpoint cannot redirect credentials offsite.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('API redirects are disabled.')
    with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=30) as response:
        raw = response.read(24*1024*1024+1)
    if len(raw) > 24*1024*1024:
        raise ValueError('Snapshot exceeds 24 MiB.')
    value = json.loads(raw)
    return value.get('datasets', value)


def bundle(datasets, start, end):
    if not isinstance(datasets, dict) or any(kind not in SCHEMAS for kind in datasets):
        raise ValueError('Snapshot must map supported dataset names to record arrays.')
    files = {}
    for kind, rows in datasets.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Each dataset must be an array of records.')
        columns = set(SCHEMAS[kind]['required']+SCHEMAS[kind]['optional'])
        scoped = [{key: value for key, value in row.items() if key in columns} for row in rows]
        files[kind] = {'filename': kind+'.json', 'format': 'json', 'content': json.dumps(scoped)}
    result = validate_submission(files, start, end)
    if not result['valid']:
        raise ValueError(json.dumps(result['issues']))
    return {'period_start': start, 'period_end': end, 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--sqlite', help='Read-only exported SQLite file, never a continuous source.')
    source.add_argument('--json-snapshot', help='JSON dataset dictionary from a periodic API/database export.')
    source.add_argument('--api-url', help='One explicit request to localhost/private IP inside the controlled network.')
    parser.add_argument('--tables', help='JSON mapping supported dataset names to SQLite table names.')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error('Choose a new output filename.')
    try:
        if args.sqlite:
            data = sqlite_snapshot(args.sqlite, json.loads(Path(args.tables).read_text()) if args.tables else None)
        elif args.json_snapshot:
            value = json.loads(Path(args.json_snapshot).read_text())
            data = value.get('datasets', value)
        else:
            data = api_snapshot(args.api_url)
        value = bundle(data, args.start, args.end)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, indent=2), encoding='utf-8')
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))
    print(f'Periodic bundle ready: {output}. Select an entity and load this bundle in Import.')


if __name__ == '__main__':
    main()
