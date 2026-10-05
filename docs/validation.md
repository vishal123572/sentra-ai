# Validation methodology and results

Run `python3 validate.py` from the project directory to execute the Python suite, optional JavaScript render/action checks (if Node is installed) and a synthetic performance measurement. The application itself does not need Node. Results are written to `docs/validation-results.json`.

## Automated checks

- Detector evidence IDs match independently planted synthetic labels for rapid closures, missing escalation, repeated narratives, coverage gaps, unavailable referenced cases, closure outliers and SLA-edge evidence.
- A synthetic healthy baseline, including legitimate automated fast closures, produces no findings.
- Missing optional files remain unassessed and never imply a healthy score.
- Zero alerts do not imply missing monitoring coverage.
- Invalid timelines, duplicate IDs, invalid booleans, invalid policy and column mapping are exercised.
- Assessment intervals use an exclusive end. Stale/future coverage is distinguished from activity valid at period end.
- Repeated imports are rejected; policy snapshots and examiner decisions survive reopening the database.
- Concurrent-review versions prevent an old decision overwriting a newer one.
- A modified audit event is detected. Reports escape HTML and protect CSV cells against common formula prefixes.
- HTTP tests exercise login, cookies, CSRF, same-origin login, unauthenticated access, reader permissions, upload, analysis, evidence, review, reports and logout.
- An assessment/review/report workflow succeeds with all socket connection attempts blocked.
- JavaScript checks render the seven existing views, the joined entity assessment, record/finding tabs and untrusted explanation text escaping.
- Service tests verify unique, detector-balanced selection; overlapping case reasons; negative-space source evidence; review-aware samples; historical peer cohorts; different file types despite equal file percentages; and exclusion of empty eligible peer populations.
- JavaScript event-handler integration uses a disposable actual HTTP server to run login, validation, import, assessment, sample selection, record/source drill-down, examiner decision, refreshed evidence and HTML export. DOM objects are stubs, so this is an action/API integration check rather than browser interaction or visual QA.

## Performance measurement

The included measurement ingests 10,000 alerts and 10,000 cases plus inventory, coverage, escalation, expectation and workflow records. It records wall time and peak Python allocations with `tracemalloc`. This is one synthetic in-process batch, not concurrent HTTP load or production sizing. Hardware and tracing overhead affect the result.

## What these results establish

The checks demonstrate the implemented rules, storage and API behaviour on representative synthetic fixtures. They do not establish accuracy on genuine SOC exports or equivalence to expert manual assessment. No unsupported precision/recall claims are made.

Browser interaction/visual QA and Docker execution remain unverified. The cloud browser could not reach the loopback test server. Source/render/API and frontend action integration checks passed; run the following acceptance checks on the target demonstration laptop before presenting:

1. Start with `--demo`, sign in and inspect all navigation views.
2. Open Atlas Grid's assessment, inspect index contributions and peer rates, open the recommended sample, inspect record explanations/timeline/source and save a finding-group decision.
3. Upload the sample CSV exports into a newly registered entity; validate and assess.
4. Inspect Northstar's missing coverage and referenced case records; export each report format and print the HTML report to PDF.
5. Restart the application and confirm saved decisions remain.
6. Disconnect the laptop from Internet access and repeat the workflow.

## Expert validation plan

Before operational use, obtain a permitted, pseudonymised set of genuine periodic exports. Have multiple SOC practitioners label supervisory issues independently while blinded to tool results. Reconcile disagreement with recorded reasons. Separate tuning periods from a held-out evaluation set.

Measure finding precision, recall against expert-labelled issue groups, confirmed finding yield under a fixed review-time budget, examiner time and false-positive causes. Compare prioritised review against random and stratified manual sampling. Report confidence intervals and data limitations; do not report synthetic planted-label performance as real-world efficacy.


The Evidence Investigation release also verifies quartile calculations on a seven-minute case outside the fixed threshold; excludes legitimate strong investigations from SLA-edge findings; leaves small baselines unassessed; preserves older engine snapshots; excludes linked alert/asset flags from independent samples even after dismissal; saves concurrent-versioned independent observations; includes their history in HTML/JSON; and exercises the new UI actions against an actual disposable HTTP server. A narrative recovery concern is deliberately not auto-detected to demonstrate why independent human review remains necessary.

The 1.3 release additionally tests explicit category/workflow/oversight/recovery signals against planted IDs, approved exceptions, missing exports, late events, exploratory feature profiles, read-only SQLite conversion and schema-only field retention. Expert-label tests cover adjudication/tuning exclusions, duplicate/unknown labels, record-level confusion counts, report persistence and audit events. Frontend action checks include loading a periodic bundle, downloading blinded records and uploading comparison labels. The authoritative current test count and measured batch timing are in `validation-results.json`.
