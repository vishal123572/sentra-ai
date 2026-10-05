# SIH26157 implementation coverage — release 1.3.0

This is a deployable demonstration. Implementation and synthetic checks are complete within the stated bounds; effectiveness on genuine CSE data requires external expert validation.

| Requirement | Implementation / evidence | Limit |
|---|---|---|
| 1–3: multi-entity structured ingestion, common formats, multiple periods | Seven CSV/JSON schemas, mapping, read-only SQLite export and one-shot internal API/JSON adapters; stored entity/period history | Memory-bound, 24-MiB requests and 100,000 rows/file; no production-scale certification |
| 4–6: detection/investigation/escalation weaknesses, execution gaps, negative space | Thirteen versioned detectors with explicit policy, workflow and monitoring expectations | Missing exports remain unassessed; evidence absence requires completeness clarification |
| 7: anomalies/outliers/suspicious patterns | Closure IQR, SLA-edge cluster and exploratory same-severity multi-feature profiles | Candidate hypotheses; no automatic intent or universal unknown-threat detection |
| 8: peers | Same period/sector/size/policy/file types; at least two eligible peers | Cohort comparability still needs examiner context |
| 9: entity indicators | Explained affected/eligible attention index, availability and eight domain evidence indicators | Review heuristic, not calibrated breach probability or capability certification |
| 10: review priorities | Entity/group attention and detector-balanced deduplicated samples; independent unflagged sampling | Fixed bounded recommendations; no automated supervisory verdict |
| 11–14: explanation, evidence, traceability, flag rationale | Evidence Investigation, expected/observed checks, timelines, linked original records, source hashes and preserved policies | References are submitted assertions; privileged owner can rewrite audit chain |
| 15–17: dashboards/reports/trends/drill-down | Seven app views, joined assessments, period-normalised activity context, HTML/CSV/JSON reports, evidence detail | Target-browser visual QA outstanding |
| Offline deployment | Bundled Python-standard-library application, SQLite, local assets; socket-blocked workflow passes | Python/browser must be provided locally; Docker and proxy templates unexecuted |
| AI/ML controls | No trained/neural model, cloud inference or GPU; deterministic offline statistical profiles with stored fences and reviewed source updates | Genuine efficacy still requires a held-out study |
| Validation against manual review | Blinded export, adjudicated labels, persisted confusion/precision/recall/review yield with label hash | Actual qualified expert labels are not supplied or fabricated |
| Infrastructure/operation | Local launchers, accounts, backups, service/TLS/container examples and upgrade instructions | Production load/security assurance and site sizing remain operator work |
| Source/setup | Complete source archive, README, schemas, methodology and tests | GitHub/Drive public source link requires the chosen publication destination |

All eight capability areas have evidence indicators: Detection, Investigation, Escalation, Response, Security operations, Governance, Operational discipline and Cyber resilience. They do not cover every aspect of those capabilities. No real-time SOC, SIEM, national monitoring or continuous telemetry platform is built.

Presentation, two-page architecture PDF and video are excluded from this software-only completion scope at the user's request. The architecture and design remain documented in source markdown for deployment and review.
