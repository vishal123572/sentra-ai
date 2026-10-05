# SAT-SA architecture and functional design

**Purpose:** prioritise supervisory assessment of periodic SOC exports while preserving human judgement. No real-time collection or continuous monitoring is used.

## Local architecture

Browser UI (bundled HTML/CSS/JavaScript) → authenticated same-origin HTTP API → normalisation/validation → deterministic detectors → SQLite persistence → examiner review and report export.

The Python standard-library application serves both UI assets and the API. Original exports, normalised datasets, source manifests, assessment policy snapshots, metrics, evidence identifiers, examiner reviews and audit events remain in local SQLite. The package has no pip/npm/CDN/cloud dependency. A supplied Python runtime and browser are prerequisites.

## Components

| Component | Responsibility |
|---|---|
| `app/analytics.py` | Data schemas, CSV/JSON normalisation, structural validation, thirteen detectors, attention rates and domain metrics. |
| `app/service.py` | Entity and policy operations, assessment persistence, evidence drill-down, reviews, sampling and reports. |
| `app/supervisory.py` | Joined summaries, historical peer cohorts, index explanations, indexed record context and deterministic detector-balanced review selection. |
| `app/patterns.py` | Same-severity, multi-feature IQR profile discovery with stored feature fences. |
| `app/evaluation.py` | Blinded review export and adjudicated held-out label comparison. |
| `tools/import_bundle.py` | Periodic SQLite, JSON and internal API snapshot adapters. |
| `app/storage.py` | SQLite schema, transactions, PBKDF2 password hashing and hash-linked audit records. |
| `app/server.py` | Local HTTP routing, sessions, roles, CSRF checks, body limits and security headers. |
| `app/demo.py` | Reproducible synthetic exports and independently specified planted signal IDs. |
| `web/` | Responsive dashboard, entity register, import mapping, findings, evidence review, reports and methodology. |

## Analytics methodology

Rules identify unsupported rapid closures, required escalations absent from the export, repeated normalised narratives across assets, recurring asset/category alerts without a remediation reference, documented coverage gaps on critical assets, alert references to unavailable case records, IQR closure outliers with weak evidence, SLA-edge acknowledgements linked to weak investigations, activity below justified asset/category expectations, missing required investigation/oversight workflow evidence, unresolved recovery validation and unusual multi-feature profiles.

Each finding contains rule version, rationale, affected records, denominator, signal type, priority, limitations and evidence IDs. Examiners confirm, dismiss or request clarification with a mandatory reason. Concurrent saves use a version check to prevent stale overwrites.

The attention index averages assessable affected/eligible rule rates. Non-assessable capabilities remain separate and are never scored as healthy. Peer context requires at least two other entities with the exact period, sector, size band, preserved policy and supplied file types, selecting one newest matching assessment per other entity. Each metric needs eligible populations in two peers; the aggregate index also requires the same eligible-detector set. Historical-period cohorts are supported. These are explanatory review indicators, not statistically calibrated resilience scores.

Review attention is separate from the numeric index: High means at least one non-dismissed high-priority finding; Moderate means other non-dismissed findings; Incomplete means unavailable capabilities without open findings; otherwise No open signals. It is a workload label, not a risk or resilience rating. Review decisions update this label and the pending sample, without rewriting stored rule results.

Up to eight recommended records cover available pending/clarification detectors first, then fill by severity, highest signal priority and overlapping detectors. Alert findings are linked to their submitted cases where possible; cases are deduplicated. Alerts and assets remain review items when no case applies. Stable kind/ID ties and explicit point breakdowns make selection reproducible. The independent hash-based sample excludes direct case and linked alert/asset findings. Examiner observations have append-only history, stale-write protection and audit events; HTML/JSON reports preserve them.

## Explainability and auditability

Preserved source-file hashes and policy/engine snapshots make analysis reproducible. Evidence pagination exposes supporting records and linked alert/case/escalation/coverage data. Review history is append-only through the application. Audit chaining detects modifications to individual stored events; it is not protected against a privileged owner rewriting the whole database and chain. Production assurance would require an external protected audit anchor.

Record drill-down contrasts expected evidence with observed closure duration, note length, escalation counts, narrative matches, recurring alert references or coverage freshness. It exposes a timestamped alert/case/escalation timeline, missing referenced case IDs, the original source manifest and the normalised dataset position. Related collections and timelines are capped at 100 visible records, with full counts; finding evidence retains pagination. Decisions apply to finding groups. Missing evidence is a hypothesis for export clarification, not proof that an activity never occurred.

The Evidence Investigation view combines affected-record tables, expected evidence, peer rates, detector context and source-file presence before a reason-required decision. Prior-period alerts/day changes are context only, not a learned anomaly or coverage inference.

## Deployment and infrastructure

Demonstration starting point: Python 3.10+, modern browser, 2 CPU cores, 4 GB RAM and 1 GB free storage. These are planning requirements, not validated production sizing. Request processing is memory-based and limited to 24 MiB and 100,000 rows per file. Multiple entities and periods are supported. A Python local deployment was tested; Docker and internal TLS templates are supplied for operator validation.

Isolation Forest now trains locally within each submitted severity cohort. Its 64-tree architecture, CPU runtime, input features, offline dependency preparation, training hashes, sensitivity explanations and update controls are specified in `ai-model.md`. No externally hosted inference is used. The online judging demo additionally uses Vercel and Postgres; the local deployment uses SQLite.

## Coverage of the problem statement

Implemented: structured multi-entity submissions, execution-gap and negative-space signals, entity/process/sample priorities, constrained peer comparison, period comparison, evidence rationale, traceability, reporting and local deployment.

Prototype limits: supported database exports are SQLite or schema-mapped JSON/CSV, rather than vendor-specific connectors. Profile discovery proposes unusual evidence combinations, not semantic understanding of every unknown weakness. No automatic policy-document interpretation, production scalability certification or genuine expert-labelled efficacy is claimed. Each of the eight domains has an evidence indicator, but indicators do not comprehensively measure the capabilities.

Blinded export and adjudicated label comparison are implemented in the UI and CLI. Comparisons persist precision/recall, confusion counts, fixed-budget prioritised versus seeded baseline yield and label hashes. These are record-level measures, not issue-group recall or statistically significant proof of superiority. The source archive is ready to publish; an external GitHub/Drive link requires a chosen publication destination.

## Validation

The package includes automated analytics/service/HTTP tests, source-render checks, planted synthetic labels, a performance measurement and an outbound-network-disabled workflow check. These demonstrate implementation behaviour, not effectiveness on genuine CSE records. Before operational use, compare blinded expert findings with the tool on held-out real exports; measure precision, recall, review yield, examiner time and resource use.
