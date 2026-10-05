# Periodic ingestion adapters

All commands run on an approved preparation machine or inside the controlled network. They produce a local bundle; there is no scheduler, ongoing telemetry feed or Internet dependency. Supported fields are retained and unneeded fields removed. Then select an entity in Import, load the bundle, validate and explicitly run assessment.

## Exported SQLite database

Use tables named alerts, cases, escalations, assets, coverage, expectations and workflow. Missing optional tables are omitted. The source is opened read-only. For other names, pass `--tables mapping.json`, a JSON dictionary such as `{ "alerts": "soc_alerts", "cases": "soc_cases" }`; map all tables you want included. Convert PostgreSQL/SQL Server/vendor exports to the supported CSV/JSON schema first; arbitrary vendor databases are not directly connected.

```bash
python3 tools/import_bundle.py --sqlite exported.sqlite3 --start 2026-09-01 --end 2026-10-01 --output september-bundle.json
```

## Periodic JSON snapshot

Use a dictionary of dataset names to record arrays, or wrap it as `{ "datasets": { ... } }`.

```bash
python3 tools/import_bundle.py --json-snapshot snapshot.json --start 2026-09-01 --end 2026-10-01 --output september-bundle.json
```

## Explicit internal API request

The endpoint returns the same JSON snapshot. Use localhost or an explicit private IP. Redirects and embedded credentials are rejected. An optional bearer token is read from `SATSA_IMPORT_API_TOKEN`; it is not written to the bundle. The command fetches once, with a 30-second timeout and 24-MiB response cap. Internal TLS certificates must be trusted locally. No public endpoint or continuous collection is needed.

```bash
python3 tools/import_bundle.py --api-url http://127.0.0.1:9000/periodic-export --start 2026-09-01 --end 2026-10-01 --output september-bundle.json
```

Each output path must be new. Inputs are limited to 100,000 rows per dataset; split larger exports into suitably bounded assessments rather than claiming untested production scale. Schema, time and explicit empty-export semantics are in `data-contract.md`.
