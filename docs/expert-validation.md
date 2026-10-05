# Expert comparison protocol

1. Select permitted pseudonymised genuine periodic exports and separate tuning periods from held-out periods before examining results. Verify export completeness and policy expectations.
2. In an assessment, download the blinded review ZIP. It contains original normalised datasets and policy context, with blank in-period case/alert and inventory asset labels. Detector findings, index and rankings are omitted. Experts must not already have inspected the tool's conclusions if the study is to be blinded.
3. Have multiple qualified reviewers examine the same records independently. Reconcile disagreements, recording an expert reason and optional issue ID. Set `expert_concern` true or false, `adjudicated` true, and `split` held_out only after adjudication. Keep unreviewed rows blank; use tuning for development labels.
4. Upload the CSV/JSON in the assessment's comparison panel. Unknown/duplicate adjudicated records and out-of-period labels are rejected. Only adjudicated held-out rows enter the calculation. Undefined precision/recall appears unavailable.
5. Examine confusion counts, record-level precision/recall, and concerns found within the same labelled scope under a fixed record budget. The baseline is a reproducible seed-42 hash ordering without excluding flagged records. It is one baseline, not a significance test. Prioritised results use stored detector output, ignoring subsequent group decisions, so decisions do not rewrite validation predictions.
6. Export HTML/JSON reports. Persisted comparison includes label SHA-256, actor, time, engine and limitations. The application records a comparison audit event, without changing examiner findings.

Direct flags and linked alert/asset flags count as record-level predictions. These metrics do not measure issue-group recall, examiner independence, time savings or full-population efficacy. Unlabelled records are excluded, not treated as negative examples. To establish supervisory effectiveness, additionally compare issue-group findings, random and stratified sampling over repeated seeds, fixed-time examiner yield, confidence intervals and false-positive causes. Genuine expert review is external evidence and cannot be created by synthetic fixtures.

CLI alternative:

```bash
python3 tools/expert_review.py --database data/satsa.sqlite3 --submission SUBMISSION_ID --output new-blind-folder
python3 tools/expert_review.py --database data/satsa.sqlite3 --submission SUBMISSION_ID --labels adjudicated.csv --budget 8 --output new-comparison.json
```

The CLI comparison writes an evaluation file; the UI comparison additionally persists the result and audit event in the workspace. Synthetic labels included in tests only validate calculation behaviour and must never be described as real SOC expert validation.
