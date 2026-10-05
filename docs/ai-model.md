# SENTRA AI: Isolation Forest implementation

The application uses 13 explainable policy/statistical detectors plus a separate Isolation Forest model. AI candidates do not change the attention index and are not automatically confirmed supervisory findings.

## Architecture and training

Scikit-Learn Isolation Forest uses 64 trees, a maximum of 256 training samples per tree, automatic contamination threshold, seed 26157 and one worker. Each assessment trains locally on its own closed cases, grouped by effective severity. At least 20 non-approved cases with varying feature values are required per cohort. Approved automation/exception cases are excluded. Rows are sorted by case ID before fitting. Numerical inputs use log1p: closure duration, investigation-note character count, linked alert count and workflow-event count when that export is supplied. This is unsupervised within-submission outlier detection, not a model trained on proven failures or a validated cross-period normal baseline.

## Explainability and audit

Negative decision scores produce exploratory candidates. For each displayed candidate, the UI shows source case ID, score, observed features, cohort medians and the score change when each individual feature is replaced by its cohort median. These sensitivity explanations are not causal attribution. Metadata records library versions, parameters, effective sample sizes and SHA-256 of the exact cohort feature matrix. Original exports, period and model results persist in the existing assessment; re-analysis creates a new version. JSON and HTML reports include model outputs. At most 25 candidates are displayed per severity cohort, while total candidate counts remain visible.

## Offline runtime and updates

Prepare dependencies on a connected staging machine with `python -m pip download -r requirements-ml.txt -d wheels`. Transfer the wheel directory and requirements file, then install inside the controlled network with `python -m pip install --no-index --find-links wheels -r requirements-ml.txt`. Prepare wheels for the target Python version, operating system and CPU architecture. Fitting and scoring use local data and make no requests to hosted AI services. Without ML libraries, rule analytics remains available and AI is explicitly marked unavailable. Docker installs dependencies at image-build time; transfer the completed image for offline operation.

Models run on CPU; no GPU is required. Start demo sizing at 2 CPU cores and 4 GB RAM, then measure on permitted representative exports. This is planning guidance, not certified production capacity. Update model code/dependencies through reviewed source or container bundles, validate on held-out expert-labelled exports, and retain old assessment snapshots and library provenance.

## Limitations

Unusual records can represent legitimate work or export differences. Decision scores are neither breach probabilities nor validated resilience scores. The model does not semantically understand investigation narratives. Real-world accuracy and superiority to expert manual sampling remain unproven. DBSCAN and autoencoders are not implemented.
