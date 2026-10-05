import csv
import hashlib
import html
import io
import json
import secrets
import sqlite3
from .analytics import DEFAULT_POLICY, DETECTORS, ENGINE_VERSION, SCHEMAS, analyse, timestamp, validate_policy, validate_submission
from .storage import Store, dumps, now
from .version import APPLICATION_VERSION
from .diagnostics import assessment_diagnostics
from .ai import analyse_ai
from .supervisory import EvidenceIndex, ID_FIELDS, INPUTS, peer_benchmark, supervisory_summary


class ServiceError(Exception):
    def __init__(self, message, status=400, details=None):
        self.message, self.status, self.details = message, status, details


class Service:
    def __init__(self, store):
        self.store = store

    def entity_create(self, data, actor):
        name = str(data.get("name", "")).strip()
        sector = str(data.get("sector", "")).strip()
        size = data.get("size_band", "medium")
        if not 2 <= len(name) <= 100 or not sector or len(sector) > 80 or size not in {"small", "medium", "large"}:
            raise ServiceError("Provide a name (2–100 characters), sector and valid size band.")
        policy = validate_policy(data.get("policy"))
        entity_id = "ENT-" + secrets.token_hex(4).upper()
        try:
            with self.store.transaction() as db:
                db.execute("INSERT INTO entities VALUES(?,?,?,?,?,?)", (entity_id, name, sector, size, dumps(policy), now()))
                Store.audit(db, actor, "entity.created", {"entity_id": entity_id, "name": name})
        except sqlite3.IntegrityError:
            raise ServiceError("An entity with this name already exists.", 409)
        return {"id": entity_id}

    def entity_policy(self, entity_id, data, actor):
        policy = validate_policy(data)
        with self.store.transaction() as db:
            if not db.execute("SELECT id FROM entities WHERE id=?", (entity_id,)).fetchone():
                raise ServiceError("Entity not found.", 404)
            db.execute("UPDATE entities SET policy=? WHERE id=?", (dumps(policy), entity_id))
            Store.audit(db, actor, "policy.updated", {"entity_id": entity_id, "policy": policy})
        return {"policy": policy, "message": "Saved. Existing assessments keep their original policy snapshot."}

    def validate(self, data):
        result = validate_submission(data.get("files"), data.get("period_start"), data.get("period_end"))
        return {k: v for k, v in result.items() if k != "datasets"}

    def ingest(self, data, actor, *, predecessor=None, policy_snapshot=None, reason=None):
        entity_id = data.get("entity_id")
        with self.store.connect() as db:
            entity = db.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if not entity:
            raise ServiceError("Select an existing entity.", 404)
        result = validate_submission(data.get("files"), data.get("period_start"), data.get("period_end"))
        if not result["valid"]:
            raise ServiceError("Validation failed. Correct the indicated records before assessment.", 422, self.validate(data))
        analysis = analyse(result["datasets"], policy_snapshot if policy_snapshot is not None else json.loads(entity["policy"]), data["period_start"], data["period_end"])
        analysis['metrics']['ai_analysis'] = analyse_ai(result['datasets'], data['period_start'], data['period_end'])
        checksum = hashlib.sha256(dumps({"files": data["files"], "start": timestamp(data["period_start"]).isoformat(), "end": timestamp(data["period_end"]).isoformat(), "policy": analysis["policy"], "engine_version": ENGINE_VERSION}).encode()).hexdigest()
        submission_id = "SUB-" + secrets.token_hex(5).upper()
        payload = {"validation": {k: v for k, v in result.items() if k != "datasets"}, "datasets": result["datasets"],
                   "metrics": analysis["metrics"], "policy": analysis["policy"], "engine_version": ENGINE_VERSION}
        if predecessor:
            payload['reanalysis'] = {'predecessor_id': predecessor, 'reason': reason, 'policy_basis': 'Preserved predecessor policy, with defaults for newly introduced fields'}
        try:
            with self.store.transaction() as db:
                db.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?)", (submission_id, entity_id, timestamp(data["period_start"]).isoformat(), timestamp(data["period_end"]).isoformat(), checksum, now(), actor, dumps(payload), dumps(data["files"])))
                for f in analysis["findings"]:
                    finding_id = "FND-" + secrets.token_hex(5).upper()
                    db.execute("INSERT INTO findings(id,submission_id,payload,status) VALUES(?,?,?,?)", (finding_id, submission_id, dumps(f), "pending"))
                Store.audit(db, actor, "assessment.created", {"submission_id": submission_id, "entity_id": entity_id, "checksum": checksum, "rows": result["row_count"], "findings": len(analysis["findings"]), "engine_version": ENGINE_VERSION, "predecessor_id": predecessor, "reason": reason})
        except sqlite3.IntegrityError:
            with self.store.connect() as db:
                existing = db.execute('SELECT id FROM submissions WHERE entity_id=? AND checksum=?', (entity_id, checksum)).fetchone()
            raise ServiceError("This exact submission and policy have already been assessed. Open the stored assessment to see its results.", 409,
                               {'submission_id': existing['id']} if existing else None)
        return {"id": submission_id, "findings": len(analysis["findings"]), "rows": result["row_count"], "metrics": analysis["metrics"], "engine_version": ENGINE_VERSION}

    def reanalyse(self, submission_id, data, actor):
        reason = str(data.get('reason', '')).strip()
        if not 5 <= len(reason) <= 4000:
            raise ServiceError('Provide a re-analysis reason (5–4,000 characters).')
        row, payload, _ = self._assessment_source(submission_id)
        return self.ingest({'entity_id': row['entity_id'], 'period_start': row['period_start'], 'period_end': row['period_end'],
                            'files': json.loads(row['original_files'])}, actor, predecessor=submission_id,
                           policy_snapshot=payload['policy'], reason=reason)

    def state(self):
        entities, submissions, findings = [], [], []
        with self.store.connect() as db:
            for row in db.execute("SELECT * FROM entities ORDER BY name"):
                entities.append({**dict(row), "policy": json.loads(row["policy"])})
            for row in db.execute("SELECT s.*, e.name entity_name,e.sector,e.size_band FROM submissions s JOIN entities e ON e.id=s.entity_id ORDER BY s.period_end DESC,s.created_at DESC"):
                p = json.loads(row["payload"])
                submissions.append({k: row[k] for k in ["id", "entity_id", "entity_name", "sector", "size_band", "period_start", "period_end", "created_at", "actor", "checksum"]} | {"metrics": p["metrics"], "validation": p["validation"], "policy": p["policy"], "engine_version": p['engine_version'], 'reanalysis': p.get('reanalysis'), 'diagnostics': assessment_diagnostics(p, row['period_start'], row['period_end'])})
            for row in db.execute("SELECT f.*,s.entity_id,s.period_end,e.name entity_name FROM findings f JOIN submissions s ON s.id=f.submission_id JOIN entities e ON e.id=s.entity_id ORDER BY s.period_end DESC"):
                p = json.loads(row["payload"])
                p.pop("evidence_ids", None)
                findings.append(p | {k: row[k] for k in ["id", "submission_id", "entity_id", "entity_name", "period_end", "status", "comment", "reviewed_by", "reviewed_at", "version"]})
        latest = {}
        for s in submissions:
            latest.setdefault(s["entity_id"], s)
            related = [f for f in findings if f["submission_id"] == s["id"]]
            s["supervisory"] = supervisory_summary(s, related)
            s["peer_benchmark"] = peer_benchmark(s, submissions)
        for e in entities:
            e["latest_submission"] = latest.get(e["id"])
            e["peer_context"] = "No comparable entities with this period, sector and size band."
            s = latest.get(e["id"])
            if s:
                benchmark = s["peer_benchmark"]
                median = benchmark["index_median"]
                e["peer_context"] = f"{benchmark['cohort_size']} comparable peers; at least two eligible peers needed per metric. " + (f"Peer index median: {median:g}." if median is not None else "Index benchmark unavailable.")
                if median is not None:
                    e["peer_median"] = median
        return {"entities": entities, "submissions": submissions, "findings": findings, "detectors": DETECTORS, "schemas": SCHEMAS,
                "default_policy": DEFAULT_POLICY, "engine_version": ENGINE_VERSION, "application_version": APPLICATION_VERSION, "audit": self.store.verify_audit(),
                "score_method": "Mean of affected/eligible rates across assessable detectors with eligible records; range 0–100. Review-priority index, not breach probability or a validated resilience rating. Missing capabilities are shown separately."}

    def _assessment_source(self, submission_id):
        with self.store.connect() as db:
            row = db.execute("SELECT s.*,e.name entity_name FROM submissions s JOIN entities e ON e.id=s.entity_id WHERE s.id=?", (submission_id,)).fetchone()
            if not row:
                raise ServiceError("Submission not found.", 404)
            findings = [json.loads(f["payload"]) | {key: f[key] for key in ["id", "status", "comment", "reviewed_by", "reviewed_at", "version"]}
                        for f in db.execute("SELECT * FROM findings WHERE submission_id=? ORDER BY id", (submission_id,))]
        return dict(row), json.loads(row["payload"]), findings

    def assessment(self, submission_id, state=None):
        state = state or self.state()
        summary = next((s for s in state["submissions"] if s["id"] == submission_id), None)
        if not summary:
            raise ServiceError("Submission not found.", 404)
        row, payload, findings = self._assessment_source(submission_id)
        index = EvidenceIndex(payload, row["period_start"], row["period_end"])
        selection = index.selection(findings)
        return {"submission": summary, "findings": [f for f in state["findings"] if f["submission_id"] == submission_id],
                "selection": selection, "independent_sample": self.sample(submission_id),
                "activity_context": self.activity_context(summary, state["submissions"]),
                "engine_version": payload["engine_version"], "running_engine_version": ENGINE_VERSION, "application_version": APPLICATION_VERSION, "supervisory_version": APPLICATION_VERSION}

    @staticmethod
    def activity_context(target, submissions):
        prior = [s for s in submissions if s['entity_id'] == target['entity_id'] and timestamp(s['period_end']) <= timestamp(target['period_start']) and
                 all(s[key] == target[key] for key in ['policy']) and
                 {m['kind'] for m in s['validation']['manifests']} == {m['kind'] for m in target['validation']['manifests']}]
        if not prior:
            return {"available": False, "reason": "No earlier non-overlapping assessment with matching policy and file types."}
        previous = max(prior, key=lambda s: (s['period_end'], s['created_at']))
        daily = lambda s: s['metrics']['alerts'] / ((timestamp(s['period_end']) - timestamp(s['period_start'])).total_seconds() / 86400)
        old, current = daily(previous), daily(target)
        change = (current / old - 1) * 100 if old else None
        return {"available": True, "previous_submission_id": previous['id'], "previous_alerts": previous['metrics']['alerts'],
                "previous_daily_rate": round(old, 3), "current_daily_rate": round(current, 3), "change_percent": round(change, 1) if change is not None else None,
                "attention": change is not None and change <= -50,
                "reason": "Activity fell by at least half; confirm export completeness, exposure and monitoring changes." if change is not None and change <= -50 else "Compare activity with the prior submitted period.",
                "limitation": "One prior period is directional context, not a learned anomaly baseline. No inference of missing telemetry from alert volume; excluded from the attention index."}

    def submission(self, submission_id):
        with self.store.connect() as db:
            row = db.execute("SELECT s.*,e.name entity_name FROM submissions s JOIN entities e ON e.id=s.entity_id WHERE s.id=?", (submission_id,)).fetchone()
        if not row:
            raise ServiceError("Submission not found.", 404)
        p = json.loads(row["payload"])
        return {"id": row["id"], "entity_name": row["entity_name"], "period_start": row["period_start"], "period_end": row["period_end"], "checksum": row["checksum"], "created_at": row["created_at"], "validation": p["validation"], "metrics": p["metrics"], "policy": p["policy"], "engine_version": p['engine_version']}

    def finding(self, finding_id, offset=0, limit=50):
        with self.store.connect() as db:
            row = db.execute("SELECT f.*,s.entity_id,s.payload submission_payload,s.period_start,s.period_end,e.name entity_name FROM findings f JOIN submissions s ON s.id=f.submission_id JOIN entities e ON e.id=s.entity_id WHERE f.id=?", (finding_id,)).fetchone()
            if not row:
                raise ServiceError("Finding not found.", 404)
            reviews = [dict(r) for r in db.execute("SELECT * FROM reviews WHERE finding_id=? ORDER BY created_at DESC", (finding_id,))]
        f = json.loads(row["payload"])
        payload = json.loads(row["submission_payload"])
        ids = f["evidence_ids"][offset:offset + limit]
        idset = set(ids)
        datasets = payload["datasets"]
        unit = f["unit"]
        main_kind, field = {"cases": ("cases", "case_id"), "assets": ("assets", "asset_id"), "alerts": ("alerts", "alert_id")}[unit]
        primary = [r for r in datasets.get(main_kind, []) if r[field] in idset]
        case_ids = {r.get("case_id") for r in primary if r.get("case_id")}
        asset_ids = {r.get("asset_id") for r in primary if r.get("asset_id")}
        linked_alerts = [a for a in datasets.get("alerts", []) if a.get("case_id") in case_ids or (unit == "assets" and a["asset_id"] in asset_ids)][:200]
        linked_cases = [c for c in datasets.get("cases", []) if c["case_id"] in case_ids]
        linked_escalations = [e for e in datasets.get("escalations", []) if e["case_id"] in case_ids]
        linked_coverage = [c for c in datasets.get("coverage", []) if c["asset_id"] in asset_ids]
        linked_assets = [a for a in datasets.get("assets", []) if a["asset_id"] in asset_ids]
        index = EvidenceIndex(payload, row["period_start"], row["period_end"])
        summary = next(s for s in self.state()['submissions'] if s['id'] == row['submission_id'])
        peer = next(m for m in summary['peer_benchmark']['metrics'] if m['detector'] == f['detector'])
        required = INPUTS[f['detector']]
        present = {m['kind'] for m in payload['validation']['manifests']}
        evidence_rows = [{"record_id": record[field], "kind": main_kind, "severity": index.severity(main_kind, record),
                          "closed_at": record.get('closed_at'), "opened_at": record.get('opened_at'),
                          "asset_id": index.asset_id(main_kind, record), "case_id": record.get('case_id'),
                          "escalation_count": len(index.escalations[record.get('case_id')]),
                          "coverage_count": len(index.coverage[record.get('asset_id')])} for record in primary]
        return f | {k: row[k] for k in ["id", "submission_id", "entity_id", "entity_name", "period_start", "period_end", "status", "comment", "reviewed_by", "reviewed_at", "version"]} | {
            "evidence": {"kind": main_kind, "records": primary, "linked_alerts": linked_alerts, "linked_cases": linked_cases,
                         "linked_escalations": linked_escalations, "linked_coverage": linked_coverage, "linked_assets": linked_assets,
                         "offset": offset, "limit": limit, "total": len(f["evidence_ids"])},
            "record_explanations": [{"record_id": record[field], **index.explain(f["detector"], record)} for record in primary],
            "policy": payload["policy"], "manifests": payload["validation"]["manifests"], "reviews": reviews,
            "investigation": {"rows": evidence_rows, "peer": peer, "peer_criteria": summary['peer_benchmark']['criteria'],
                              "required_inputs": required, "supplied_inputs": [kind for kind in required if kind in present],
                              "input_presence_percent": round(sum(kind in present for kind in required) / len(required) * 100),
                              "checksum": summary['checksum'], "export_completeness_confirmed": False}}

    def record(self, submission_id, kind, record_id):
        if kind not in ID_FIELDS:
            raise ServiceError("Choose cases, alerts or assets.")
        row, payload, findings = self._assessment_source(submission_id)
        index = EvidenceIndex(payload, row["period_start"], row["period_end"])
        primary = index.maps[kind].get(record_id)
        if not primary:
            raise ServiceError("Record not found in this submission.", 404)
        alerts = ([primary] if kind == "alerts" else index.alerts_by_case[record_id] if kind == "cases" else index.alerts_by_asset[record_id])
        case_ids = {alert.get("case_id") for alert in alerts if alert.get("case_id")}
        if kind == "cases":
            case_ids.add(record_id)
        cases = [index.maps["cases"][case_id] for case_id in sorted(case_ids) if case_id in index.maps["cases"]]
        asset_ids = {index.asset_id(kind, primary)} | {alert["asset_id"] for alert in alerts}
        assets = [index.maps["assets"][asset_id] for asset_id in sorted(asset_ids) if asset_id in index.maps["assets"]]
        escalation_records = [e for case_id in sorted(case_ids) for e in index.escalations[case_id]]
        coverage = [c for asset_id in sorted(asset_ids) for c in index.coverage[asset_id]]
        workflow = [e for case_id in sorted(case_ids) for e in index.workflow[case_id]]
        expectations = [e for asset_id in sorted(asset_ids) for e in index.expectations[asset_id]]
        alert_ids = {alert["alert_id"] for alert in alerts}
        signals = []
        for finding in findings:
            unit = finding["unit"]
            linked_ids = {record_id} if unit == kind else alert_ids if kind == "cases" and unit == "alerts" else set()
            matches = [value for value in finding["evidence_ids"] if value in linked_ids]
            if matches:
                signals.append({key: finding[key] for key in ["id", "detector", "title", "kind", "priority", "status", "summary", "rationale", "limitations", "comment", "reviewed_by", "reviewed_at"]} |
                               {"matched_evidence_ids": matches, "explanations": [{"record_id": value, **index.explain(finding["detector"], index.maps[unit][value])} for value in matches[:20]], "explanations_total": len(matches)})
        timeline = []
        for collection, fields, identifier in [(alerts, ["created_at", "acknowledged_at"], "alert_id"), (cases, ["opened_at", "closed_at"], "case_id"), (escalation_records, ["escalated_at"], "escalation_id"), (workflow, ['performed_at'], 'event_id')]:
            for record in collection:
                for key in fields:
                    if record.get(key):
                        timeline.append({"at": record[key], "event": record.get('event_type') or key.replace("_at", "").replace("_", " "), "record_id": record[identifier]})
        timeline.sort(key=lambda event: (event["at"], event["record_id"], event["event"]))
        bundle = {"alerts": alerts, "cases": cases, "assets": assets, "escalations": escalation_records, "coverage": coverage, 'workflow': workflow, 'expectations': expectations}
        source = next((m for m in payload["validation"]["manifests"] if m["kind"] == kind), None)
        return {"submission_id": submission_id, "entity_name": row["entity_name"], "period_start": row["period_start"], "period_end": row["period_end"],
                "kind": kind, "record_id": record_id, "record": primary, "effective_severity": index.severity(kind, primary),
                "signals": signals, "linked": {key: values[:100] for key, values in bundle.items()}, "linked_totals": {key: len(values) for key, values in bundle.items()},
                "timeline": timeline[:100], "timeline_total": len(timeline), "missing_referenced_cases": sorted(case_ids - set(index.maps["cases"])),
                "source": source, "normalised_record_number": index.positions[kind][record_id], "checksum": row["checksum"],
                "policy": payload["policy"], "manifests": payload["validation"]["manifests"], "engine_version": payload["engine_version"]}

    def review(self, finding_id, data, actor):
        status, comment = data.get("status"), str(data.get("comment", "")).strip()
        if status not in {"confirmed", "dismissed", "clarification", "pending"} or not 5 <= len(comment) <= 4000:
            raise ServiceError("Choose a valid decision and provide a reason (5–4,000 characters).")
        with self.store.transaction() as db:
            row = db.execute("SELECT version FROM findings WHERE id=?", (finding_id,)).fetchone()
            if not row:
                raise ServiceError("Finding not found.", 404)
            if row["version"] != data.get("version"):
                raise ServiceError("Another examiner updated this finding. Reload it before saving.", 409)
            ts = now()
            db.execute("UPDATE findings SET status=?,comment=?,reviewed_by=?,reviewed_at=?,version=version+1 WHERE id=?", (status, comment, actor, ts, finding_id))
            db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?)", (secrets.token_hex(10), finding_id, status, comment, actor, ts))
            Store.audit(db, actor, "finding.reviewed", {"finding_id": finding_id, "status": status, "reason": comment, "version": row["version"] + 1})
        return {"saved": True}

    def sample(self, submission_id, count=5):
        row, payload, findings = self._assessment_source(submission_id)
        datasets = payload['datasets']
        index = EvidenceIndex(payload, row['period_start'], row['period_end'])
        cases = [c for c in datasets.get('cases', []) if (event := c.get('closed_at') if c['status'] == 'closed' else c['opened_at']) and
                 index.start <= timestamp(event) < index.end]
        flagged = {x for f in findings if f["unit"] == "cases" for x in f["evidence_ids"]}
        flagged_alerts = {x for f in findings if f['unit'] == 'alerts' for x in f['evidence_ids']}
        flagged_assets = {x for f in findings if f['unit'] == 'assets' for x in f['evidence_ids']}
        linked_flagged = {a.get('case_id') for a in datasets.get('alerts', []) if a['alert_id'] in flagged_alerts or a['asset_id'] in flagged_assets}
        candidates = [c for c in cases if c['case_id'] not in flagged | linked_flagged and index.asset_id('cases', c) not in flagged_assets]
        # A deterministic random sample is reproducible for an assessment.
        candidates.sort(key=lambda c: hashlib.sha256((submission_id + c["case_id"]).encode()).hexdigest())
        with self.store.connect() as db:
            observations = [dict(r) for r in db.execute('SELECT * FROM sample_observations WHERE submission_id=? ORDER BY version DESC,created_at DESC', (submission_id,))]
        return {"submission_id": submission_id, "records": candidates[:count], "population": len(candidates), "period_cases": len(cases),
                "excluded_cases": len(cases)-len(candidates), "observations": observations, "engine_version": payload['engine_version'],
                "method": "Reproducible hash-based sample of in-period cases outside all stored case findings, linked alert findings and asset findings, including dismissed findings. No claim of statistical representativeness.",
                "purpose": "Test for concerns the stored detectors may have missed. A human concern is a potential false negative requiring adjudication, not validated detector failure."}

    def sample_observation(self, submission_id, data, actor):
        sample = self.sample(submission_id)
        case_id, status, comment = data.get('case_id'), data.get('status'), str(data.get('comment', '')).strip()
        if case_id not in {c['case_id'] for c in sample['records']}:
            raise ServiceError('Choose a case in this independent sample.')
        if status not in {'no_concern', 'concern', 'needs_info'} or not 5 <= len(comment) <= 4000:
            raise ServiceError('Choose an observation and provide a reason (5–4,000 characters).')
        with self.store.transaction() as db:
            latest = db.execute('SELECT MAX(version) FROM sample_observations WHERE submission_id=? AND case_id=?', (submission_id, case_id)).fetchone()[0] or 0
            if data.get('version') != latest:
                raise ServiceError('Another examiner updated this observation. Reload before saving.', 409)
            ts = now()
            db.execute('INSERT INTO sample_observations VALUES(?,?,?,?,?,?,?,?)', (secrets.token_hex(10), submission_id, case_id, status, comment, actor, ts, latest+1))
            Store.audit(db, actor, 'independent_sample.reviewed', {'submission_id': submission_id, 'case_id': case_id, 'status': status, 'reason': comment, 'version': latest+1})
        return {'saved': True}

    def evaluate(self, submission_id, data, actor):
        from .evaluation import parse_labels, evaluate
        row, payload, findings = self._assessment_source(submission_id)
        content, filename = data.get('content'), data.get('filename', 'labels.csv')
        if not isinstance(content, str) or not isinstance(filename, str):
            raise ServiceError('Provide a CSV or JSON expert-label file.')
        result = evaluate(payload, findings, row['period_start'], row['period_end'], parse_labels(content, filename), data.get('budget', 8))
        digest = hashlib.sha256(content.encode()).hexdigest()
        identifier = 'EVAL-'+secrets.token_hex(5).upper()
        result.update({'id': identifier, 'submission_id': submission_id, 'label_sha256': digest, 'actor': actor, 'created_at': now(), 'label_source': 'User-provided adjudicated labels; reviewer expertise and independence require external confirmation.'})
        with self.store.transaction() as db:
            db.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?)', (identifier, submission_id, digest, actor, result['created_at'], dumps(result)))
            Store.audit(db, actor, 'expert_comparison.created', {'evaluation_id': identifier, 'submission_id': submission_id, 'label_sha256': digest, 'labelled_records': result['labelled_records']})
        return result

    def blind_review(self, submission_id):
        from .evaluation import blinded_package
        row, payload, _ = self._assessment_source(submission_id)
        return blinded_package(payload, submission_id, row['period_start'], row['period_end'])

    def report(self, entity_id=None, submission_id=None):
        state = self.state()
        latest_ids = {e["latest_submission"]["id"] for e in state["entities"] if e["latest_submission"]}
        subs = [s for s in state["submissions"] if (not entity_id or s["entity_id"] == entity_id) and (s["id"] == submission_id if submission_id else s["id"] in latest_ids)]
        ids = {s["id"] for s in subs}
        fs = [f for f in state["findings"] if f["submission_id"] in ids]
        with self.store.connect() as db:
            evaluations = [json.loads(r['payload']) for r in db.execute('SELECT * FROM evaluations ORDER BY created_at DESC') if r['submission_id'] in ids]
        for f in fs:
            full = self.finding(f["id"], 0, 1)
            f["evidence_ids"] = full["evidence_ids"]
            f["reviews"] = full["reviews"]
        return {"title": "SENTRA AI supervisory assessment report", "generated_at": now(), "engine_version": ENGINE_VERSION, "application_version": APPLICATION_VERSION,
                "scope": "Latest assessed period per selected entity, unless a specific submission is selected.",
                "submissions": subs, "findings": fs, "assessments": [self.assessment(s["id"], state) for s in subs], 'expert_comparisons': evaluations, "score_method": state["score_method"], "audit": state["audit"],
                "limitations": ["Prototype indicators require human examination; they are not a compliance verdict.", "Completeness measures files supplied, not the completeness or truth of the source exports.", "Synthetic demonstration data does not establish effectiveness on real SOC exports."]}


def csv_report(report):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["finding_id", "entity", "detector", "priority", "affected", "eligible", "status", "summary", "review_reason", "evidence_ids"])
    for f in report["findings"]:
        row = [f["id"], f["entity_name"], f["detector"], f["priority"], f["affected_count"], f["denominator"], f["status"], f["summary"], f["comment"], ";".join(f["evidence_ids"])]
        writer.writerow([("'" + str(x)) if str(x).startswith(("=", "+", "-", "@")) else x for x in row])
    return out.getvalue()


def html_report(report):
    esc = lambda value: html.escape(str(value))
    entities = "".join(f"<tr><td>{esc(s['entity_name'])}</td><td>{esc(s['period_start'][:10])} to {esc(s['period_end'][:10])} (end exclusive)</td><td>{esc(s['metrics']['attention_score'])}</td><td>{s['validation']['completeness']}%</td><td>{esc(s['checksum'][:16])}</td></tr>" for s in report["submissions"])
    findings = "".join(f"<article><h2>{esc(f['title'])}</h2><p><b>{esc(f['entity_name'])} · {esc(f['priority'])} · {esc(f['status'])}</b></p><p>{esc(f['summary'])}</p><p>{esc(f['rationale'])}</p><p>Evidence: {esc(', '.join(f['evidence_ids']))}</p><p>Examiner: {esc(f['reviewed_by'] or 'Awaiting review')} · {esc(f['comment'])}</p><p>Limitations: {esc(' '.join(f['limitations']))}</p></article>" for f in report["findings"])
    assessments = []
    for assessment in report.get("assessments", []):
        submission = assessment["submission"]
        summary, benchmark, selection = submission["supervisory"], submission["peer_benchmark"], assessment["selection"]
        ai = submission['metrics'].get('ai_analysis')
        if ai:
            candidates = ''.join(f"<li>{esc(c['case_id'])}: decision score {esc(c['decision_score'])}; feature sensitivity {esc(dumps(c['features']))}</li>" for c in ai['candidates'])
            findings += f"<article><h2>{esc(submission['entity_name'])}: Isolation Forest AI exploration</h2><p>{esc(ai['status'])}; {ai['flagged_count']} unusual records. Excluded from the attention index.</p><p>{esc(ai['training'])}</p><p>{esc(ai['explanation'])}</p><ul>{candidates}</ul><p>Model provenance: {esc(dumps(ai['cohorts']))}</p><p>{esc(ai['limitation'])}</p></article>"
        drivers = "".join(f"<tr><td>{esc(d['name'])}</td><td>{esc(d['affected']) if d['assessed'] else 'N/A'} / {esc(d['eligible']) if d['assessed'] else 'N/A'}</td><td>{esc(d['rate']) if d['rate'] is not None else 'N/A'}</td><td>{'Included' if d['included_in_index'] else 'Excluded'}; {esc(', '.join(d['missing_inputs']))}</td></tr>" for d in summary["drivers"])
        peer_rows = "".join(f"<tr><td>{esc(m['name'])}</td><td>{esc(m['entity_rate']) if m['entity_rate'] is not None else 'N/A'}</td><td>{esc(m['peer_median']) if m['peer_median'] is not None else 'N/A'}</td><td>{esc(m['difference_pp']) if m['difference_pp'] is not None else 'N/A'}</td><td>{m['eligible_peers']}</td></tr>" for m in benchmark["metrics"])
        sample = "".join(f"<li><b>{esc(item['record_id'])}</b> ({esc(item['kind'])}); {item['score']} review points. {esc(item['selection_reason'])} Signals: {esc(', '.join(signal['title'] for signal in item['signals']))}.</li>" for item in selection["records"])
        independent = assessment.get('independent_sample', {})
        observations = "".join(f"<li><b>{esc(o['case_id'])}</b>: {esc(o['status'])}; {esc(o['comment'])}. Examiner {esc(o['actor'])}; {esc(o['created_at'])}; version {o['version']}.</li>" for o in independent.get('observations', []))
        independent_html = f"<h3>Independent examination: check what detectors missed</h3><p>{esc(independent.get('method', ''))}</p><p>{esc(independent.get('purpose', ''))}</p><p>Selected IDs: {esc(', '.join(c['case_id'] for c in independent.get('records', [])))}</p><ol>{observations}</ol>"
        activity = assessment.get('activity_context', {})
        activity_html = (f"<h3>Prior-period activity context</h3><p>{esc(activity['current_daily_rate'])} alerts/day versus {esc(activity['previous_daily_rate'])}; change {esc(activity['change_percent'])}%. {esc(activity['reason'])}</p><p>{esc(activity['limitation'])}</p>" if activity.get('available') else '')
        assessments.append(f"<article><h2>{esc(submission['entity_name'])}: supervisory explanation</h2><p><b>{esc(summary['level'])} review attention</b>. {esc(summary['reason'])}</p><p>{esc(summary['level_method'])}</p><h3>Index contributions</h3><p>{esc(summary['method'])}</p><table><thead><tr><th>Detector</th><th>Affected / eligible</th><th>Rate %</th><th>Index treatment / missing inputs</th></tr></thead><tbody>{drivers}</tbody></table><h3>Peer context</h3><p>{benchmark['cohort_size']} matching peers. {esc(benchmark['criteria'])}</p><table><thead><tr><th>Metric</th><th>Entity %</th><th>Peer median %</th><th>Difference pp</th><th>Eligible peers</th></tr></thead><tbody>{peer_rows}</tbody></table><p>{esc(benchmark['limitation'])}</p><h3>Recommended sample</h3><p>{esc(selection['method'])}</p><ol>{sample}</ol><p>{esc(selection['limitation'])}</p></article>")
        assessments[-1] += independent_html + activity_html
    findings = "".join(assessments) + findings
    for comparison in report.get('expert_comparisons', []):
        fmt = lambda value: f'{value*100:.1f}%' if value is not None else 'N/A'
        findings += f"<article><h2>Expert-label comparison {esc(comparison['id'])}</h2><p>{comparison['labelled_records']} adjudicated held-out records. Precision {fmt(comparison['precision'])}; recall {fmt(comparison['recall'])}.</p><p>Prioritised review: {comparison['prioritised_review']['concerns_found']} concerns among {comparison['prioritised_review']['reviewed']} reviewed. Seeded baseline: {comparison['hash_baseline_review']['concerns_found']} among {comparison['hash_baseline_review']['reviewed']}.</p><p>Label SHA-256: {esc(comparison['label_sha256'])}</p><p>{esc(comparison['label_source'])}</p><ul>{''.join('<li>'+esc(x)+'</li>' for x in comparison['limitations'])}</ul></article>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>SENTRA AI Assessment Report</title><style>body{{font:16px/1.5 system-ui;color:#162238;max-width:1000px;margin:40px auto;padding:0 24px}}h1{{color:#0e7669}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;border-bottom:1px solid #ccd6df;padding:10px}}article{{break-inside:avoid;border-top:2px solid #c8d7df;margin-top:28px;padding-top:12px}}button{{padding:10px}}@media print{{button{{display:none}}body{{margin:0}}}}</style></head><body><button onclick="window.print()">Print / Save as PDF</button><h1>{esc(report['title'])}</h1><p>Generated {esc(report['generated_at'])} · Engine {esc(report['engine_version'])}</p><p>{esc(report['scope'])}</p><table><thead><tr><th>Entity</th><th>Period</th><th>Attention index</th><th>Files supplied</th><th>Submission hash</th></tr></thead><tbody>{entities}</tbody></table><p>{esc(report['score_method'])}</p>{findings}<h2>Assessment limitations</h2><ul>{''.join('<li>'+esc(x)+'</li>' for x in report['limitations'])}</ul><p>Audit chain verification: {esc(report['audit']['valid'])}. {esc(report['audit'].get('limitation',''))}</p></body></html>"""
