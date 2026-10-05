"""Locally trained exploratory Isolation Forest, separate from policy findings."""
import hashlib
import json
import math
from collections import Counter, defaultdict
from functools import lru_cache
from .analytics_time import timestamp, truth

MODEL_VERSION = '1.0.0'
MIN_COHORT = 20
FEATURES = ('closure_minutes', 'note_characters', 'linked_alerts')
PARAMETERS = {'n_estimators': 64, 'max_samples': 256, 'contamination': 'auto',
              'random_state': 26157, 'n_jobs': 1}


@lru_cache(maxsize=16)
def _fit(rows, features):
    import numpy as np
    import sklearn
    from sklearn.ensemble import IsolationForest
    raw = np.asarray([row[1:] for row in rows], dtype=np.float64)
    transformed = np.log1p(raw)
    model = IsolationForest(**(PARAMETERS | {'max_samples': min(PARAMETERS['max_samples'], len(rows))})).fit(transformed)
    decisions = model.decision_function(transformed)
    medians = np.median(raw, axis=0)
    encoded = json.dumps({'rows': rows, 'features': features}, separators=(',', ':')).encode()
    # Feature effects are counterfactual score changes, not causal attribution.
    flagged = sorted((i for i, score in enumerate(decisions) if score < 0),
                     key=lambda i: (decisions[i], rows[i][0]))
    candidates = []
    for i in flagged[:25]:
        explanations = []
        for j, feature in enumerate(features):
            variant = transformed[i:i+1].copy()
            variant[0, j] = math.log1p(float(medians[j]))
            effect = float(model.decision_function(variant)[0] - decisions[i])
            explanations.append({'feature': feature, 'observed': float(raw[i, j]),
                                 'cohort_median': float(medians[j]), 'score_change_at_median': round(effect, 6)})
        candidates.append({'case_id': rows[i][0], 'decision_score': round(float(decisions[i]), 6),
                           'features': sorted(explanations, key=lambda x: -x['score_change_at_median'])})
    return {'sklearn_version': sklearn.__version__, 'numpy_version': np.__version__, 'actual_max_samples': model.max_samples_,
            'training_sha256': hashlib.sha256(encoded).hexdigest(), 'offset': float(model.offset_),
            'flagged_count': len(flagged), 'candidates': candidates}


def analyse_ai(datasets, period_start, period_end):
    result = {'model': 'Isolation Forest', 'model_version': MODEL_VERSION,
              'parameters': PARAMETERS, 'minimum_cohort': MIN_COHORT, 'cohorts': [],
              'flagged_count': 0, 'candidates': [], 'included_in_attention_index': False,
              'training': 'Unsupervised fit on this submission, separately within effective-severity cohorts; features use log1p.',
              'explanation': 'Replacing one feature with its cohort median shows how the model score changes. This is model sensitivity, not proof of cause.',
              'limitation': 'Exploratory unusual records only. Negative decision scores are not breach probabilities, poor-quality verdicts or verified weaknesses. At most 25 examples per cohort are shown. Requires independent expert validation.'}
    try:
        import sklearn  # Optional for a minimal rules-only local installation.
    except ImportError:
        return result | {'status': 'unavailable', 'reason': 'Install the supplied offline ML dependencies to enable Isolation Forest.'}
    result['sklearn_version'] = sklearn.__version__
    start, end = timestamp(period_start), timestamp(period_end)
    linked, workflow = defaultdict(list), Counter()
    for alert in datasets.get('alerts', []):
        if start <= timestamp(alert['created_at']) < end and alert.get('case_id'):
            linked[alert['case_id']].append(alert)
    for event in datasets.get('workflow', []):
        if start <= timestamp(event['performed_at']) < end:
            workflow[event['case_id']] += 1
    severity_rank = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
    features = FEATURES + (('workflow_events',) if 'workflow' in datasets else ())
    cohorts = defaultdict(list)
    for case in datasets.get('cases', []):
        if case['status'] != 'closed' or truth(case.get('approved_automation')) or truth(case.get('approved_exception')):
            continue
        if not case.get('closed_at') or not start <= timestamp(case['closed_at']) < end:
            continue
        case_alerts = linked[case['case_id']]
        severities = [a['severity'] for a in case_alerts] + [case.get('severity') or 'info']
        severity = max(severities, key=lambda value: severity_rank[value])
        values = ((timestamp(case['closed_at']) - timestamp(case['opened_at'])).total_seconds()/60,
                  len(case.get('investigation_notes', '').strip()), len(case_alerts))
        if 'workflow' in datasets:
            values += (workflow[case['case_id']],)
        cohorts[severity].append((case['case_id'], *values))
    trained = 0
    for severity, rows in sorted(cohorts.items()):
        rows = tuple(sorted(rows))
        if len(rows) < MIN_COHORT or len({row[1:] for row in rows}) < 2:
            result['cohorts'].append({'severity': severity, 'records': len(rows), 'status': 'not_assessed',
                                      'reason': 'At least 20 eligible cases and varying feature values are required.'})
            continue
        fitted = _fit(rows, features)
        trained += 1
        result['cohorts'].append({k: v for k, v in fitted.items() if k != 'candidates'} |
                                 {'severity': severity, 'records': len(rows), 'status': 'trained', 'features': list(features)})
        result['flagged_count'] += fitted['flagged_count']
        result['candidates'].extend(candidate | {'severity': severity} for candidate in fitted['candidates'])
    result['candidates'].sort(key=lambda candidate: (candidate['decision_score'], candidate['case_id']))
    return result | {'status': 'assessed' if trained else 'insufficient_data', 'trained_cohorts': trained,
                     'decision_threshold': 0.0, 'features': list(features)}
