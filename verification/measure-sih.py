"""One bounded synthetic ingestion measurement for the SIH audit."""
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from app.demo import make_submission
from app.service import Service
from app.storage import Store, dumps

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
payload, _ = make_submission('execution', prefix='AUDIT', rows=10000)
with tempfile.TemporaryDirectory(prefix='sentra-volume-audit-') as folder:
    service = Service(Store(Path(folder) / 'volume.sqlite3'))
    entity = service.entity_create({'name': 'SYNTHETIC audit volume', 'sector': 'Energy', 'size_band': 'medium'}, 'audit')
    payload['entity_id'] = entity['id']
    payload_size = len(dumps(payload).encode('utf-8'))
    tracemalloc.start()
    started = time.perf_counter()
    result = service.ingest(payload, 'audit')
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
              'alerts': 10000, 'cases': 10000, 'source_rows': result['rows'],
              'serialized_payload_bytes': payload_size, 'ingest_seconds_with_allocation_tracing': round(elapsed, 3),
              'peak_traced_python_allocations_mib': round(peak / 1024 / 1024, 2), 'finding_groups': result['findings'],
              'fits_hosted_4_mib_request': payload_size <= 4*1024*1024,
              'fits_local_24_mib_request': payload_size <= 24*1024*1024,
              'limitation': 'One synthetic in-process SQLite import. Not a live Vercel, browser, concurrency, RSS or production-scale benchmark.'}
    Path('verification/sih-volume-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
