# SENTRA AI — Centralized Security Intelligence

A runnable offline SIH26157 demonstration prototype. Upload periodic SOC exports, detect potential execution gaps and negative space, inspect supporting evidence, preserve examiner decisions and export assessment reports.

**Release 1.4.0 / analytics engine 1.3.0:** seven periodic data types, thirteen explainable detectors, evidence indicators across all eight capability areas, database/API snapshot adapters, and a blinded expert-label comparison workflow. Existing submissions, accounts and examiner decisions remain preserved; see `docs/upgrade.md`.

**All demonstration organisations and records are synthetic. This is a supervisory assessment workbench; findings require human examination.**

## Quick start: Windows

1. Extract this entire folder.
2. Install Python 3.10+ if it is not already installed. The local rules-only application needs Python and a browser. To enable Isolation Forest, run `py -3 -m pip install -r requirements-ml.txt` before starting.
3. Double-click `start.bat`, or run the command below in the extracted folder:

```powershell
py -3 run.py --demo
```

4. Open **http://127.0.0.1:8080** in a modern browser.
5. Sign in using username **examiner** and the fixed demo password **SatSaDemo2026!**. No password is auto-generated. `SATSA_ADMIN_USER` and `SATSA_ADMIN_PASSWORD` can override the first-run credentials.
6. Keep the console open while using the application. Press Ctrl+C to stop.

## Quick start: macOS / Linux

```bash
python3 run.py --demo
```

Or run `sh start.sh`. Open http://127.0.0.1:8080 and use the first-run credentials displayed in the console.

To use a different port: `python3 run.py --demo --port 8081`.

## Your first demonstration

The `--demo` option loads three clearly labelled fictional energy-sector entities, with August and September 2026 submissions. Loading the demo again preserves existing data and decisions.

- **Meridian Energy:** a baseline with legitimate approved automated closures.
- **Atlas Grid:** unsupported rapid closures, absent required escalations, reused narratives and recurring alerts without recorded remediation.
- **Northstar Power:** gaps in documented critical-system monitoring coverage, missing escalation and unavailable referenced investigations.

1. In Overview, click **Open assessment** for Atlas Grid.
2. Inspect execution gaps, negative space, actual detector rates and the peer benchmark. The High attention label reflects non-dismissed high-priority findings, not a fabricated score or breach probability.
3. Open **Review 8 selected records**. The detector-balanced sample merges duplicate cases and explains severity, signal priority and overlapping detectors for each selection.
4. Click **Open record & explanation**. Compare expected evidence with observed values, inspect the operational timeline, full records and source/policy provenance.
5. Click **Review finding group**, select Examiner decision, request clarification and save a reason. The decision applies to the associated finding group, not a separate per-case verdict.
6. Use the back buttons to inspect the updated record and refreshed sample. Confirmed/dismissed groups leave the recommendation pool; cases with other pending signals can remain.
7. Open Northstar Power's assessment to see critical assets missing expected coverage evidence and alerts referencing unavailable cases. No alert volume assumption is used to establish a coverage gap.
8. Open **Check what the detectors missed**. Inspect independent case evidence, save an examiner observation and export HTML/JSON reports with observation history (CSV exports automated finding groups). Restart and verify saved reviews remain.

For the 2-minute walkthrough, see `docs/demo-script.md`.

## Import your own demonstration exports

1. Register an entity with its sector and size band.
2. Configure its assessment policy under Entities.
3. In Submissions, select the entity and UTC assessment interval. The end date is exclusive: September is 1 September to 1 October.
4. Attach CSV or JSON exports and map non-standard column names if necessary.
5. Validate files. Correct all errors, and review warnings.
6. Run assessment to open the complete entity assessment, including recommended records and explanations. Missing optional exports mark related detectors not assessed.

The alerts file is required. Cases, escalations, assets, coverage, expectations and workflow files are optional but needed for their associated capabilities. Header-only CSV files are accepted as explicitly empty exports. Empty JSON arrays are accepted; the examiner must confirm that these genuinely represent complete empty exports.

Download CSV templates in the app. Ready-to-import examples are in `sample-data/healthy`, `sample-data/execution` and `sample-data/coverage`, each covering September 2026. Their `expected-signals.json` files identify independently planted synthetic signals.

Full schemas: `docs/data-contract.md`.

## Included capabilities

- CSV/JSON import, source-column mapping, duplicate-ID checks, timeline checks and timezone handling.
- Thirteen explainable detectors, including IQR closure outliers, SLA-edge timing, justified expected-category absence, required investigation/oversight evidence, recovery validation and unusual multi-feature operational profiles.
- Periodic read-only SQLite exports, JSON database/API snapshots and explicit one-shot internal API ingestion via `tools/import_bundle.py`.
- Blinded review ZIP export and adjudicated held-out label upload, with record-level precision/recall, confusion counts, fixed-budget review yield, label hashes and report/audit persistence.
- Entity attention indicators, file completeness, domain matrix, historical period selection and constrained peer comparison.
- Joined entity assessment with execution-gap/negative-space panels, detector-level peer rates, eligible populations and index contributions.
- Reproducible recommended samples across case/alert/asset evidence, with per-record selection points, detector diversity and no duplicate case entries.
- Record-specific expected/observed checks, operational timelines, linked evidence and source-file/normalised-record provenance.
- Evidence pagination, linked records, source-file SHA-256 hashes and immutable assessment policy snapshots.
- Examiner decisions with required rationale, review history and concurrent-edit protection.
- Hash-linked audit history with verification and an explicit privileged-owner limitation.
- Reproducible review samples beyond case-level flags.
- Local administrator, examiner and read-only accounts; password hashing, session cookies and CSRF checks.
- Printable HTML reports, CSV findings and structured JSON assessment exports.
- Desktop/mobile responsive layouts, keyboard-accessible controls and native modal dialogs.
- Windows/macOS/Linux launchers, Docker deployment files, Linux service and internal TLS configuration examples.

## Implementation and offline operation

**Backend:** Python 3.10+ standard library HTTP application. **Database:** SQLite locally, PostgreSQL in the hosted deployment. **Analytics:** thirteen policy/statistical detectors plus a separate Scikit-Learn Isolation Forest explorer using NumPy. **Interface:** bundled HTML/CSS/JavaScript without external fonts, libraries or CDNs.

The local rules-only application has no dependency-installation step. Isolation Forest requires the supplied ML dependencies; prepare them before moving to an offline environment as described in `docs/ai-model.md`. Local processing does not call a hosted AI API. The Vercel demo uses a networked PostgreSQL database.

The database is created at `data/satsa.sqlite3`. It is not included in the delivered source archive, so your first run creates a fresh account and workspace. Protect this directory using operating-system permissions and your organisation's approved disk encryption and backup controls.

No raw packet captures or continuous telemetry collection are used.

## Accounts and administration

Create examiner and reader accounts in Methodology & audit, signed in as the administrator. Credentials are local. Eight-hour sessions expire automatically. Readers can inspect and export, but cannot import, change policy or review findings.

If you lose a password, use local shell access:

For the fixed demo login, run `python3 manage.py reset-demo-password` (Windows: `py -3 manage.py reset-demo-password`). This also updates databases created by an older version without deleting imported data. The username is **examiner**, password **SatSaDemo2026!**. Existing accounts are never silently reset on startup.

To choose your own password instead:

```bash
python3 manage.py reset-password examiner
```

The new password is entered interactively. Existing sessions for the account are revoked. Additional local accounts can also be created:

```bash
python3 manage.py create-user reviewer --role examiner
```

Create a consistent backup, including while the server runs:

```bash
python3 manage.py backup backups/satsa-backup.sqlite3
```

Restore by stopping the app and replacing the database with a consistent backup; remove old WAL/SHM sidecars only while the server is stopped. Keep backup files inside the controlled environment.

## Deployment

For a desktop demo, use the quick-start command. For an internal server, keep the Python service bound to loopback and place it behind the supplied internal TLS proxy example. See `docs/deployment.md`.

Docker, if available:

```bash
docker compose up --build -d
docker compose logs satsa
```

The image build requires the Python base image to be available. Prebuild and transfer it using `docker save` / `docker load` for an air-gapped machine. No network is needed by the running application. Docker execution was not available in the build environment; direct Python deployment was tested.

## Tests

Run the complete dependency-free Python suite:

```bash
python3 -m unittest discover -s tests -v
```

The suite covers planted signals, legitimate exceptions, missing inputs, zero-alert coverage, malformed timelines, column mapping, persistent review decisions, duplicate imports, concurrent review, audit tampering, reports, login, CSRF and read-only permissions.

Validation results and limits: `docs/validation.md`.

## Boundaries and next steps

This is a working demonstration prototype, not an approved NCIIPC production deployment. The attention index is a transparent review-priority heuristic, not calibrated breach probability or a validated national resilience rating. Peer comparison uses reporting period, sector, size, configured policy and supplied-file completeness; additional business and telemetry context remains necessary.

Detectors cover thirteen supervisory patterns, including exploratory profiles beyond predefined failure rules. Comprehensive capability assessment, statistically calibrated efficacy and real expert-labelled validation still require operational evidence and expert examination. No external model or LLM is required. Review the full capability mapping and limits in `docs/architecture.md`.

Prototype request limits: 24 MiB and 100,000 rows per file. Processing is in memory; larger production volumes require streaming ingestion and a suitable deployment architecture. Visual browser interaction QA still requires running the demo on your target machine; automated API and render checks are included.


## New analytics and validation workflow

Cases can explicitly require investigation, oversight and recovery validation. Upload their `workflow` export with timestamped events and evidence references. `expectations` records justify a minimum alert count for a specific asset/category; absent alerts alone never establish a monitoring failure. Missing exports remain unassessed. The eight domain indicators describe submitted evidence, not certification of all capabilities.

In Import, **Load periodic bundle** accepts an adapter-generated JSON bundle; loading only fills the form. Validate and run assessment explicitly. See `docs/adapters.md`.

In an assessment, **Expert-review comparison** exports records and blank labels without detector results or rankings. Have experts review independently and adjudicate differences; upload their held-out CSV/JSON labels to calculate and persist a comparison. Unreviewed and tuning labels are excluded. Synthetic labels are only a software test. See `docs/expert-validation.md`.

Upgrade instructions: `docs/upgrade.md`. Historic snapshots keep their original engine, findings and decisions. Explicit re-analysis under the current engine creates a separate assessment.

Release requirement mapping: `docs/requirements.md`. This repository includes application source, synthetic sample data, tests, and deployment configuration. Credentials and local database contents are excluded.


## Vercel deployment

SENTRA AI retains the SAT-SA assessment engine and offline launchers. Vercel serves `web/` and `api/index.py`; hosted uploads, accounts, sessions, examiner decisions and audit history persist in Postgres. Connect the free Neon integration and configure `SATSA_ADMIN_PASSWORD` before deploying with `npx --yes vercel@latest deploy --prod --yes`. `DATABASE_URL` (or `POSTGRES_URL`) is required. Local SQLite databases and credentials are excluded from deployment. The hosted workspace starts empty; register an entity and upload its exports, or explicitly load synthetic demo data.

The hosted request limit is 4 MiB including JSON encoding. Larger exports require smaller coherent bundles. Application startup does not overwrite historical assessments; use **Re-analyse stored files** to create a new assessment under the current engine. Zero findings can be a valid result; unavailable checks and evidence coverage remain visible.

The deployment uses 13 explainable detectors plus a locally trained Isolation Forest model. AI exploration is separate from the attention index. See `docs/ai-model.md` for architecture, offline dependency preparation, features, training provenance and limitations. Testing was subsequently authorized; current audit evidence is in `docs/sih-audit.md`.


AI dependencies are optional for the minimal local rules-only installation. Enable Isolation Forest with `python -m pip install -r requirements-ml.txt`, or use the offline wheel workflow in `docs/ai-model.md`. Hosted deployments include these dependencies. Existing assessments retain their earlier results; use **Re-analyse stored files** to create a new assessment containing AI exploration.
