# Input contract

Use UTF-8 CSV with a header row, or JSON arrays of objects. JSON `{ "records": [...] }` is also accepted. Column mapping is available before validation. Unknown columns are ignored by the current detector set; the original file remains stored locally.

## Alerts

Required: `alert_id`, `asset_id`, `category`, `severity`, `created_at`.

Optional: `acknowledged_at`, `case_id`.

Severity: critical, high, medium, low, info. IDs must be unique within an alert export. `created_at` determines whether the alert falls within the assessment interval.

## Cases

Required: `case_id`, `opened_at`, `status`.

Optional: `closed_at`, `asset_id`, `severity`, `investigation_notes`, `closure_reason`, `approved_automation`, `approved_exception`, `remediation_reference`, `investigation_required`, `oversight_required`, `recovery_validation_required`.

Status: open, investigating, escalated, closed. Closed cases require `closed_at`. When case severity is absent, the highest linked alert severity is used. Case severity cannot reduce a linked alert's severity. Missing asset IDs can be inferred from linked alerts for narrative analysis.

`approved_automation` and `approved_exception` must be explicit booleans. The rapid-closure and required-escalation rules exclude these approved conditions. These fields are trusted submitted assertions; supervisors should verify their authorisation. A remediation reference is evidence of a recorded follow-up, not proof that remediation succeeded.

## Escalations

Required: `escalation_id`, `case_id`, `escalated_at`. Optional: `destination_role`.

An absent file means escalation is not assessed. An explicitly empty export means no escalations were submitted; the examiner must check export completeness. The initial rule checks presence, not recipient appropriateness or escalation timeliness.

## Assets

Required: `asset_id`, `asset_type`, `criticality`, `expected_monitoring`. Optional: `name`.

Criticality: critical, high, medium, low. Monitoring expectation must be explicitly true or false. The coverage detector targets critical assets with expected monitoring true.

## Coverage

Required: `asset_id`, `monitoring_source`, `coverage_status`, `last_seen_at`.

Coverage status: active, inactive, unknown. Multiple sources per asset are allowed. An active source seen at or before period end, within the configured freshness window, establishes documented coverage. Future activity cannot establish historical coverage.

## Dates and assessment intervals

Use ISO 8601, for example `2026-09-14T12:30:00+05:30` or `2026-09-14T07:00:00Z`. Dates are converted to UTC. A missing timezone produces a warning and is interpreted as UTC. Assessment start is inclusive; end is exclusive. Cross-period cases and escalations are retained for linkage and produce warnings when appropriate.

Closed cases are assessed in their closure period. Open cases are assessed in their opening period. Recurrence examines alerts created in the selected interval. Coverage uses the submitted inventory and source activity relative to period end.

## Submission quality

Structural errors block processing: missing required columns/values, duplicate IDs, invalid dates, invalid severities or booleans, impossible timelines and invalid case/coverage statuses. Out-of-period timestamps produce warnings because historical linkage can be legitimate.

Unlinked case records are exposed as a supervisory signal with an export-completeness limitation. Missing asset references and unlinked escalation references are not currently exhaustively validated; confirm relational completeness before relying on results.

All original file hashes are retained. File completeness is the percentage of seven supported types supplied (historical assessments preserve their earlier schema count). This is a file-presence indicator, not a guarantee of complete monitoring, complete exports or correct data.

## Expectations

Required: `expectation_id`, `asset_id`, `category`, `min_alerts`, `expectation_basis`. Optional: `approved_exception`.

`min_alerts` is a whole number from 1 to 100,000 for the selected assessment interval. The basis must explain why activity is expected, for example a scheduled test or an approved monitoring contract. Match categories exactly after trimming, and reference an asset in the submitted inventory. Approved exceptions are excluded. The finding counts affected assets, not individual expectations. Missing inventory/expectation exports leave this detector unassessed. Absence of activity is evidence against this explicit expectation, not proof of an incident or broken sensor.

## Workflow

Required: `event_id`, `case_id`, `event_type`, `performed_at`. Optional: `actor_role`, `evidence_reference`, `result`.

Types: investigation, response, oversight, recovery, remediation, escalation. Result, if provided: success, failed, unknown. Required-step flags on cases must be explicit booleans. A required investigation needs a linked investigation event with an evidence reference between opening and closure. Oversight additionally requires an actor role. Recovery uses the latest referenced recovery event in that interval and requires success. Approved automation/exceptions are excluded from these required-step rules. The existing escalation detector uses the separate escalation export; a workflow event alone does not satisfy it. Evidence references are recorded assertions, not verification that work actually occurred.

## Periodic bundles

An adapter bundle contains `period_start`, `period_end`, and `files`, keyed by these seven supported types. Each file has `filename`, `format` (`json`/`csv`) and text `content`. Loading a bundle in Import never automatically runs analysis. The adapter strips fields outside the schema; direct uploads preserve original files locally, so remove customer information before submitting.
