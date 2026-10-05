# Evidence Investigation analytics (package 1.3.0 / engine 1.2.0)

Signals are hypotheses for examiners. Thresholds and input assumptions are explicit; no external AI or probabilistic resilience rating is used.

## Two new signals

**Closure distribution outlier:** collect in-period closed-case durations, excluding approved automation and exceptions. Require at least 20 baseline closures. Compute inclusive quartiles Q1 and Q3, IQR = Q3 − Q1, and lower fence = Q1 − 1.5 × IQR. Flag high/critical eligible cases strictly below that fence only when trimmed notes have fewer than 40 characters or closure rationale is absent. The denominator is eligible non-approved high/critical closures; the baseline population includes all eligible severities. Q1, Q3, fence and population are stored with the finding. No distribution fit or learned model is used. Unequal case complexity can explain a duration outlier.

**SLA-edge acknowledgements:** use in-period alerts with an acknowledgement and a linked case closed in this period, excluding approved automation and exceptions. Require at least 20 eligible acknowledgements. A cluster requires at least 10 and at least half of these acknowledgements within [90%, 100%] of the entity's configured acknowledgement SLA (default 30 minutes). Within that cluster, flag only alerts whose linked closed case has fewer than 40 trimmed note characters or no closure rationale. The denominator is all eligible acknowledgements. Store edge count, eligible count, window and SLA. Batching, timestamp semantics and operational procedure may explain the cluster. Timing is not evidence of gaming or intent. Confirm the SLA with the entity; it is a configurable demonstration assumption.

Both signals use reproducible calculations and record-level explanations. Missing inputs or small baselines remain unassessed. The stored index includes their affected/eligible rates only when assessed and non-empty; overlapping rules are disclosed, so the index is not an independent-probability calculation. Do not compare historical indices without matching detector eligibility and preserved policy.

## Context and independent examination

Prior-period activity uses alerts/day to account for unequal period lengths. Select the latest earlier non-overlapping submission for the same entity, preserved policy and supplied file types. A reduction of at least 50% prompts a contextual review message. A zero previous rate makes percentage change unavailable. One prior period cannot establish a robust normal baseline. Activity context does not affect the index and never establishes missing telemetry.

Independent samples use an assessment-specific hash ordering of in-period cases, excluding every case directly flagged or linked to a flagged alert or asset. Dismissed findings remain excluded because those records have already been selected by the detector. Up to five cases are selected reproducibly. Their examiner observations have reason, actor, timestamp, version, append-only history and audit events. A concern is a potential false negative requiring expert adjudication. This small sample is not a statistically representative estimate of recall.

Input-file presence is distinct from source completeness. An escalation export's presence does not establish that every escalation was exported. The escalation peer metric shows recorded escalation presence among eligible closed cases, not verified policy compliance. Empty denominators or fewer than two eligible peers show unavailable comparisons.

## Deliberate synthetic scenarios

| Fixture | Scenario | Demonstrated evidence |
|---|---|---|
| Atlas September | Rapid weak closures, missing escalation, copied notes, recurring alerts without remediation references | Original six rules with record IDs, denominator and preserved policy |
| Atlas September case `ATL-09-CASE-0111` | Seven-minute weak closure | Distribution outlier beyond the fixed two-minute rapid-closure threshold |
| Atlas September acknowledgements | Timing concentrated at 29.5 minutes with weak linked investigations | SLA-edge hypothesis, with cluster count and explicit intent limitation |
| Northstar September | Three critical inventory assets lack coverage records; alert references lack cases | Expected evidence and source absence, with export-clarification prompts |
| Northstar August → September | 160 → 40 alerts | Period-normalised activity context, excluded from the index |
| Meridian September case `MER-09-CASE-0021` | Narrative says recovery test is still failing and vendor follow-up is pending | Human-only review prompt: structured detectors produce no automated finding |
| Any entity independent sample | Cases outside direct and linked stored findings | Full evidence and saved examiner observations to check for overlooked concerns |

The Meridian case can remain outside the five-case hash sample; sampling does not guarantee discovery of every concern. Its ID is deliberately documented for examiner-led validation. No synthetic planted-label result establishes expert-level efficacy on genuine SOC exports.

## Updates and validation

Old assessments are immutable snapshots. Engine 1.0.0 results mark the two additional detectors as not implemented rather than silently treating them as healthy. Explicit re-import under engine 1.1.0 creates a separate assessment; source identity includes engine version. Existing decisions, user accounts and observations are retained.

Run `python3 validate.py` for deterministic labels, legitimate controls, small baselines, peer availability, historical compatibility, independent sampling, observation concurrency, audit, offline workflow and frontend/API integration. Genuine operational validation still requires blinded expert labels, held-out periods and a comparison of review yield under a fixed time budget.

## Explicit expectations and workflow evidence (engine 1.2.0)

Expected-category absence compares in-period asset/category alert counts with a justified submitted minimum, excluding approved exceptions. Only inventory-linked expectations are eligible. Its denominator is distinct eligible assets. Required investigation and oversight checks use in-period closed cases with the corresponding explicit requirement true, excluding approved automation/exceptions. Referenced events must be between opening and closure; oversight also requires an actor role. Required recovery checks use the latest referenced recovery event in that interval and require success. Missing files or zero eligible populations remain unavailable rather than healthy.

## Exploratory operational profiles

For each severity cohort, require at least 20 in-period non-approved closed cases. Features are closure minutes, trimmed note length, linked alert count and workflow-event count when that export is supplied. Inclusive Q1/Q3 fences are Q1 − 1.5 IQR and Q3 + 1.5 IQR. A candidate has at least two features strictly outside their fences. Store the same-severity baseline count, observed values, quartiles and fences. This unsupervised distribution method has no labelled training, neural architecture, GPU or remote inference. It discovers combinations beyond named failure rules, but large cohorts, case complexity, constant features and export quality affect interpretation. No anomaly alone proves a weakness.

Atlas case `ATL-09-CASE-0152` has a long closure and unusual unique narrative length. Profile discovery identifies it beyond the fixed rapid-closure, missing-escalation, reused-note, short-closure and SLA-edge rules. Atlas also contains required investigation and oversight gaps; Northstar contains explicitly expected but absent scheduled-test categories and failed required recovery validation. These are synthetic scenario tests, not genuine CSE conclusions.

Updates remain reviewed source releases, installed offline after regression testing. Engine 1.2.0 re-imports create separate snapshots; old results are never silently rescored. Expert comparison protocol and statistical limits are documented in `expert-validation.md`.
