"""Offline distribution-based profile discovery, without failure-pattern labels."""
import statistics
from collections import defaultdict
from .analytics_time import timestamp, truth


def operational_profiles(cases, links, workflow):
    cohorts = defaultdict(list)
    for c in cases:
        if c['status'] != 'closed' or truth(c.get('approved_automation')) or truth(c.get('approved_exception')):
            continue
        values = {'closure_minutes': (timestamp(c['closed_at'])-timestamp(c['opened_at'])).total_seconds()/60,
                  'note_characters': len(c.get('investigation_notes', '').strip()),
                  'linked_alerts': len(links.get(c['case_id'], []))}
        if workflow is not None:
            values['workflow_events'] = len(workflow.get(c['case_id'], []))
        cohorts[c['severity']].append((c, values))
    eligible, details = [], {}
    for severity, cohort in cohorts.items():
        if len(cohort) < 20:
            continue
        fences = {}
        for feature in cohort[0][1]:
            q1, _, q3 = statistics.quantiles([v[feature] for _, v in cohort], n=4, method='inclusive')
            fences[feature] = {'q1': q1, 'q3': q3, 'lower': q1-1.5*(q3-q1), 'upper': q3+1.5*(q3-q1)}
        for c, values in cohort:
            eligible.append(c['case_id'])
            unusual = {k: {'observed': v, **fences[k]} for k, v in values.items() if v < fences[k]['lower'] or v > fences[k]['upper']}
            if len(unusual) >= 2:
                details[c['case_id']] = {'severity_cohort': severity, 'baseline_count': len(cohort), 'unusual_features': unusual}
    return eligible, details
