# SENTRA AI SIH26157 audit — 5 October 2026

## Verdict

The core supervisory workflow is implemented and passes bounded local tests. This is a demonstration prototype, not proof that all SIH success criteria have been met. The online site is the judging demo; an optional local installation supports the controlled offline environment. This audit does not recommend removing the online demo.

Release audited: application 1.4.0, analytics engine 1.3.0. Actual stack: Python standard-library HTTP backend; PostgreSQL online / SQLite locally; Python rules and statistics with NumPy and Scikit-Learn Isolation Forest; HTML/CSS/JavaScript frontend; Vercel judging demo and Docker/Python local deployment. FastAPI, Pandas, React, Tailwind, DBSCAN and autoencoders are not implemented.

## Fresh verification

- 78 Python tests passed in 41.055 seconds. Tests cover all 13 detectors, supplied TestEnergy fixtures, input validation, periods, peer criteria, authentication, roles, CSRF, immutable evidence, concurrent review updates, source hashes, audit integrity, reports and expert-label arithmetic. Three new tests cover AI reproducibility, exclusions, insufficient cohorts, sensitivity explanations and persistence.
- Frontend render checks passed for seven main screens, assessment/record/finding views and untrusted text escaping.
- Actual frontend event handlers passed against a disposable local HTTP service: login, bundle load, validation, assessment import, exact result selection, repeated upload, filter clearing, same-engine re-analysis, ranked sample, evidence/timeline views, examiner decisions, independent observations, blinded export, expert-label comparison and HTML download. DOM objects were stubbed; this is not a visual browser test.
- Offline import, review and report paths passed with outbound socket connections blocked.
- The supplied TestEnergy exports contain 381 source records. Core policy/statistical analysis correctly produces one exploratory profile finding for TE-CS-0022 rather than invented failures. Missing optional inputs remain explicitly unassessed. AI exploration is reported separately.
- Existing Vercel production logs contained HTTP 200 responses for health, login, workspace state and synthetic demo loading, and the expected HTTP 401 before login. Historical logs are supporting evidence only, not direct end-to-end cloud testing.
- Direct access to the deployed site through the browser tool was denied by its permission policy. No alternative route was used to circumvent that denial. Live browser layout, upload interactions and mobile behavior remain unverified.

## Functional requirements

| SIH requirement | Audit result | Qualification |
|---|---|---|
| 1. Multiple CSE ingestion | Covered in local tests | Distinct entities, policies, submissions and assessments |
| 2. CSV, JSON, exports and APIs | Covered within supported formats | CSV/JSON, read-only SQLite conversion and one-shot private API snapshots; no generic vendor connectors |
| 3. Large datasets and multiple periods | Partial | Multiple periods tested; one bounded volume measurement, no production load assurance |
| 4. Detection/investigation/escalation weaknesses | Covered as indicators | Findings require examiner interpretation |
| 5. Execution gaps | Covered | Explicit configured policies and supplied workflow requirements; no automatic policy-document interpretation |
| 6. Negative space | Covered within submitted evidence | Expected activity, coverage and missing references; incomplete exports remain a caveat |
| 7. Anomalies and suspicious patterns | Covered as exploratory candidates | IQR/SLA profiles plus separately trained Isolation Forest; unknown weaknesses are not guaranteed |
| 8. Peer comparison | Covered | Exact compatible cohort and at least two eligible other entities |
| 9. Entity supervisory indicators | Covered | Review attention index, not calibrated cyber-risk probability |
| 10. Review priorities | Covered with limits | Entity ranking, domain matrix, finding queue and detector-balanced samples; no comprehensive control inventory |
| 11. Clear rationale | Covered | Observed/expected rules plus AI feature sensitivity |
| 12. Supporting evidence | Covered | Linked source records and identifiers |
| 13. Traceability and auditability | Covered within prototype | Source hashes, policies, model training hashes, versions and hash-linked audit; privileged database rewrite remains possible |
| 14. Understand why flagged | Covered | Rule thresholds, evidence, cohort context and AI sensitivity; no automatic verdict |
| 15. Dashboards and reports | Covered locally | Heatmap, ranking, findings, HTML/CSV/JSON; deployed visual QA pending |
| 16. Trends | Basic coverage | Period trends and normalised prior-period activity; not learned forecasting |
| 17. Evidence drill-down | Covered locally | Findings to linked records and reconstructed submitted-event timeline |

## Remaining SIH evidence gaps

1. Real expert-validation results. The blinded package and comparison machinery are implemented, but there is no held-out study demonstrating comparable or better effectiveness than expert manual sampling. Synthetic tests do not establish accuracy, recall, examiner-time savings or supervisory assurance on real CSE data.
2. Large-volume judging workflow. The current online request cap is 4 MiB including JSON encoding. The measured 10,000-alert/10,000-case synthetic bundle contains 44,208 total source rows and 8,412,049 bytes, so it does not fit one hosted request. Smaller coherent period bundles are necessary until chunked or object-storage ingestion is implemented.
3. Scalability evidence. Before adding AI, the single local SQLite measurement took 10.13 seconds with allocation tracing and peaked at 64.58 MiB traced Python allocations. This is not a Vercel/Postgres/AI/concurrency benchmark. No production-capacity claim is justified.
4. Submission artifacts. Source, README, architecture/design/methodology/data/deployment documentation and a demo script exist. A published source-code link, architecture artifact verified at no more than two pages, finished video verified at no more than two minutes and final presentation verified at no more than five slides were not found in the inspected project. External artifacts may exist elsewhere and were not verified.
5. Docker runtime execution and live-browser QA remain unverified. The local HTTP workflow is tested; Docker has a supplied build configuration and now installs local ML dependencies at preparation time.

## Judge-facing AI use

Isolation Forest is now real implementation, not a presentation-only claim. Open a newly imported assessment, or use **Re-analyse stored files** on an earlier assessment, to display the AI exploration panel. Existing snapshots remain unchanged. The panel shows unusual case candidates, source evidence, model scores, feature sensitivity, training cohorts and provenance. At least 20 eligible varying cases per severity cohort are needed. AI candidates remain separate from the policy finding count and attention index. See `ai-model.md` for offline preparation and model controls.

## Evidence files

- `verification/python-audit.log`
- `verification/local-frontend-audit.json`
- `verification/sih-volume-audit.json`
- `tests/test_ai.py`

Initial issues found and corrected: the HTTP test had a stale assertion for the version-tagged JavaScript URL; the frontend test VM omitted the real TextEncoder API; the audit runner needed explicit UTF-8 console output on Windows. These were test-harness fixes, not hidden application failures.
