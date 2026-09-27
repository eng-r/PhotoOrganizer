import csv
import html
import json
from collections import Counter
from dataclasses import asdict

from . import __version__
from .models import jsonable


def write_json(path, value):
    with path.open("w", encoding="utf-8") as stream:
        json.dump(jsonable(value), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def write_csv(path, rows, columns):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {}
            for key in columns:
                value = row.get(key, "")
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value  # spreadsheet formula injection protection
                safe[key] = value
            writer.writerow(safe)


class AuditWriter:
    def __init__(self, process):
        self.process = process

    def snapshot(self, config, state):
        write_json(self.process / "config_snapshot.json", config.data)
        write_json(self.process / "_AuditTrail/run_context.json", {
            "schema_version": 1, "tool_version": __version__, "run_id": state.run_id,
            "validation_clock": state.started, "exiftool_version": state.metadata_version})

    def analysis(self, state, include_plan):
        plan_by_source = {p.media.relative_path: p for p in state.plan}
        records, rows = [], []
        for media in state.inventory.eligible:
            entry = plan_by_source.get(media.relative_path)
            timestamp = state.timestamps.get(media.relative_path) or (entry.timestamp if entry else None)
            records.append({"schema_version": 1, "media": jsonable(media), "timestamp": jsonable(timestamp),
                            "destination_relative_path": entry.destination if entry else None,
                            "resolved_date": timestamp.value.date().isoformat() if timestamp and timestamp.value else None,
                            "daily_primary_media_count": entry.daily_primary_media_count if entry else None,
                            "day_classification": entry.day_classification if entry else None,
                            "month_folder": entry.month_folder if entry else None,
                            "day_folder": entry.day_folder if entry else None,
                            "media_role": media.media_role, "storage_leaf": entry.storage_leaf if entry else None,
                            "associated_primary": media.associated_primary})
            if timestamp:
                t = timestamp.value
                rows.append({"source_relative_path": media.relative_path, "selected_timestamp": t.isoformat() if t else "",
                             "selected_source_category": timestamp.category, "selected_source_field": timestamp.source_field,
                             "confidence": timestamp.confidence, "timezone_known": timestamp.timezone_known,
                             "precision": timestamp.precision, "year": t.year if t else "", "month": t.month if t else "", "day": t.day if t else "",
                             "daily_primary_media_count": entry.daily_primary_media_count if entry else "",
                             "day_classification": entry.day_classification if entry else "",
                             "media_role": media.media_role, "storage_leaf": entry.storage_leaf if entry else "",
                             "destination_relative_path": entry.destination if entry else "", "warnings": timestamp.warnings})
        with (self.process / "_AuditTrail/manifest.jsonl").open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        write_csv(self.process / "_AuditTrail/timestamp_audit.csv", rows,
                  ["source_relative_path", "selected_timestamp", "selected_source_category", "selected_source_field", "confidence",
                   "timezone_known", "precision", "year", "month", "day", "daily_primary_media_count", "day_classification",
                   "media_role", "storage_leaf", "destination_relative_path", "warnings"])
        if include_plan:
            write_csv(self.process / "reports/plan.csv", [{"source_relative_path": p.media.relative_path,
                      "destination_relative_path": p.destination, "size": p.media.size,
                      "daily_primary_media_count": p.daily_primary_media_count, "day_classification": p.day_classification,
                      "media_role": p.media_role, "storage_leaf": p.storage_leaf,
                      "associated_primary": p.associated_primary} for p in state.plan],
                      ["source_relative_path", "destination_relative_path", "size", "daily_primary_media_count",
                       "day_classification", "media_role", "storage_leaf", "associated_primary"])

    def copy_result(self, result):
        with (self.process / "_AuditTrail/copy_results.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")


NOT_ARCHIVED_COLUMNS = ["source_relative_path", "destination_relative_path", "disposition", "destination_presence",
                        "reason", "explanation", "failed_stage", "attempt_count"]


def build_not_archived(state):
    planned = {p.media.relative_path: p for p in state.plan}
    issues = {i["path"]: i for i in state.reconciliation.issues if i["reason"] in ("DESTINATION_MISSING", "DESTINATION_MISMATCH", "SOURCE_CHANGED", "SOURCE_DISAPPEARED")}
    rows = []
    for media in state.inventory.files:
        name = media.relative_path
        entry, copied, issue = planned.get(name), state.copies.get(name), issues.get(name)
        destination = entry.destination if entry else ""
        # A successful publication is insufficient if the final scan disproves it.
        if copied and copied.success and not issue and state.reconciliation.complete:
            continue
        presence = "NOT_CHECKED"
        if state.reconciliation.complete and destination:
            presence = "PRESENT_UNVERIFIED" if destination in state.reconciliation.destination else "ABSENT"
        if not media.eligible:
            disposition = ("UNASSOCIATED_SIDECAR" if media.reason == "UNASSOCIATED_SIDECAR" else
                           "UNSUPPORTED" if media.media_role == "UNSUPPORTED" else "IGNORED")
            reason, explanation = media.reason, media.detail
        elif name in state.collisions:
            disposition, reason, explanation = "FAILED", "PLAN_COLLISION", "multiple sources map to the same destination"
        elif copied and not copied.success:
            disposition = "NOT_ATTEMPTED" if not copied.attempt_count else "FAILED"
            reason, explanation = copied.reason, copied.error
        elif issue:
            disposition, reason, explanation = "UNCONFIRMED", issue["reason"], issue["detail"]
        elif copied and copied.success:
            disposition, reason, explanation = "UNCONFIRMED", "INTERRUPTED" if state.interrupted else "RECONCILIATION_INCOMPLETE", "copy verified and published, but final recount was not completed"
        elif state.interrupted:
            disposition, reason, explanation = "NOT_ATTEMPTED", "INTERRUPTED", "run interrupted before confirmed archive result"
        elif state.fatal:
            disposition, reason, explanation = "NOT_ATTEMPTED", "NOT_ATTEMPTED_PREFLIGHT_FAILURE" if state.stage != "COPY" else "NOT_ATTEMPTED_RUN_ABORTED", state.fatal
        else:
            disposition, reason, explanation = "NOT_ATTEMPTED", "ANALYSIS_ONLY", "no media copying requested"
        rows.append(dict(zip(NOT_ARCHIVED_COLUMNS, [name, destination, disposition, presence, reason, explanation,
                         copied.stage if copied else state.stage if media.eligible else "DISCOVERY",
                         copied.attempt_count if copied else 0])))
    return sorted(rows, key=lambda r: (r["source_relative_path"].casefold(), r["source_relative_path"]))


def summarize(config, state, missing):
    copies = list(state.copies.values())
    if state.interrupted:
        status, code = "INTERRUPTED", 3
    elif state.fatal:
        status, code = "FAIL", 2
    elif state.errors or (state.command == "run" and state.reconciliation.status != "PASS"):
        status, code = "FAIL", 1
    elif state.warnings or not state.inventory.eligible:
        status, code = "WARN", 0
    else:
        status, code = "PASS", 0
    primary_plan = [p for p in state.plan if p.media_role == "PRIMARY_MEDIA"]
    sidecar_plan = [p for p in state.plan if p.media_role == "SIDECAR"]
    dates = [t.value for t in state.timestamps.values() if t.value]
    return {"schema_version": 1, "status": status, "exit_code": code, "command": state.command,
            "completed_stage": state.completed_stage, "last_stage": state.stage, "run_id": state.run_id, "tool_version": __version__,
            "source_root": str(config.source_root), "destination_root": str(config.destination_root),
            "started": state.started, "ended": state.ended,
            "inventory_complete": state.inventory_complete, "reconciliation": state.reconciliation.status,
            "reconciliation_complete": state.reconciliation.complete,
            "primary_media_reconciliation": state.reconciliation.primary_status,
            "sidecar_reconciliation": state.reconciliation.sidecar_status,
            "source_media_total": sum(f.recognized for f in state.inventory.files),
            "source_media_ignored": sum(f.recognized and not f.eligible for f in state.inventory.files),
            "source_media_eligible": len(state.inventory.eligible), "planned_media": len(state.plan),
            "source_media_recount": len(state.reconciliation.source.eligible) if state.reconciliation.status != "NOT_RUN" else None,
            "successful_copies": sum(r.success for r in copies),
            "failed_copies": sum(not r.success and r.attempt_count > 0 for r in copies),
            "not_attempted_copies": sum(not r.success and r.attempt_count == 0 for r in copies),
            "destination_media_recount": len(state.reconciliation.destination) if state.reconciliation.status != "NOT_RUN" else None,
            "bytes_planned": sum(p.media.size for p in state.plan), "bytes_copied": sum(r.source_size for r in copies if r.success),
            "primary_media_count": len(state.inventory.primary_media),
            "sidecar_count": sum(f.media_role == "SIDECAR" for f in state.inventory.files),
            "associated_sidecar_count": len(state.inventory.associated_sidecars),
            "unassociated_sidecar_count": sum(f.reason == "UNASSOCIATED_SIDECAR" for f in state.inventory.files),
            "cr2_primary_media_count": sum(p.media.path.suffix.lower() == ".cr2" for p in primary_plan),
            "day_folder_count": len({(p.timestamp.value.date(), p.day_folder) for p in primary_plan if p.day_classification == "DAY_FOLDER"}),
            "sparse_day_count": len({p.timestamp.value.date() for p in primary_plan if p.day_classification == "SPARSE"}),
            "sparse_primary_media_count": sum(p.day_classification == "SPARSE" for p in primary_plan),
            "unknown_date_primary_media_count": sum(p.day_classification == "UNKNOWN_DATE" for p in primary_plan),
            "planned_primary_media": len(primary_plan), "planned_associated_sidecars": len(sidecar_plan),
            "verified_primary_media": sum(state.copies.get(p.media.relative_path) is not None and state.copies[p.media.relative_path].success for p in primary_plan),
            "verified_associated_sidecars": sum(state.copies.get(p.media.relative_path) is not None and state.copies[p.media.relative_path].success for p in sidecar_plan),
            "destination_primary_media_recount": len(state.reconciliation.primary_destination) if state.reconciliation.status != "NOT_RUN" else None,
            "destination_sidecar_recount": len(state.reconciliation.sidecar_destination) if state.reconciliation.status != "NOT_RUN" else None,
            "year_count": len({d.year for d in dates}),
            "unknown_date_count": sum(t.value is None for t in state.timestamps.values()),
            "timestamp_sources": dict(Counter(t.category for t in state.timestamps.values())),
            "not_archived_count": len(missing), "not_archived_reasons": dict(Counter(r["reason"] for r in missing)),
            "not_archived_dispositions": dict(Counter(r["disposition"] for r in missing)),
            "space_preflight": state.space, "error_count": len(state.errors), "warnings": state.warnings,
            "fatal_error": state.fatal}


def table(rows, columns):
    if not rows:
        return '<p class="empty">None.</p>'
    head = "".join(f"<th>{html.escape(c.replace('_', ' ').title())}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(c, '')))}</td>" for c in columns) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def daily_audit_rows(state):
    rows = {}
    for entry in state.plan:
        if entry.timestamp.value is None:
            continue
        day = entry.timestamp.value.date()
        row = rows.setdefault(day, {
            "date": day.isoformat(), "primary_media": entry.daily_primary_media_count,
            "sidecars": 0, "classification": entry.day_classification,
            "destination": f"{day.year:04d}/{entry.month_folder}/{entry.day_folder}",
        })
        if entry.media_role == "SIDECAR":
            row["sidecars"] += 1
    return [rows[day] for day in sorted(rows)]


class HtmlReportWriter:
    def write(self, path, summary, state, missing, coverage):
        esc = html.escape
        cards = "".join(f'<div class="card"><span>{esc(label)}</span><strong>{summary[key]}</strong></div>' for label, key in
                        [("Primary media", "primary_media_count"), ("Associated sidecars", "associated_sidecar_count"),
                         ("Day folders", "day_folder_count"), ("Files not archived", "not_archived_count")])
        months = Counter(f"{p.timestamp.value.year:04d}/{p.month_folder}" for p in state.plan if p.timestamp.value and p.media_role == "PRIMARY_MEDIA")
        daily = daily_audit_rows(state)
        overview = {k: summary[k] for k in ("primary_media_count", "sidecar_count", "associated_sidecar_count",
                    "unassociated_sidecar_count", "planned_primary_media", "planned_associated_sidecars",
                    "verified_primary_media", "verified_associated_sidecars", "day_folder_count", "sparse_day_count",
                    "sparse_primary_media_count", "unknown_date_primary_media_count", "cr2_primary_media_count",
                    "failed_copies", "not_attempted_copies", "year_count", "bytes_planned", "bytes_copied", "exit_code")}
        facts = "".join(f"<dt>{esc(k.replace('_', ' '))}</dt><dd>{esc(str(v))}</dd>" for k, v in overview.items())
        links = [("../logs/photo_organizer.txt", "TXT execution log"), ("summary.json", "JSON summary"), ("not_archived.csv", "Not archived CSV"),
                 ("errors.csv", "Errors CSV"), ("ignored_files.csv", "Ignored files CSV"), ("plan.csv", "Plan CSV"),
                 ("../_AuditTrail/manifest.jsonl", "Manifest"), ("../_AuditTrail/timestamp_audit.csv", "Timestamp audit"),
                 ("../_AuditTrail/copy_verification.csv", "Copy verification"), ("../_AuditTrail/reconciliation.csv", "Reconciliation")]
        anchors = " ".join(f'<a href="{url}">{label}</a>' for url, label in links if (path.parent / url).is_file())
        doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Photo Archive Organizer — {summary['status']}</title><style>
:root{{font-family:Segoe UI,system-ui,sans-serif;color:#183044;background:#f1f5f9}}body{{max-width:1200px;margin:auto;padding:32px 20px}}header{{padding:24px 0}}h1{{font-size:32px;margin:8px 0}}h2{{font-size:21px}}.muted,span{{color:#52677b}}.badge{{display:inline-block;background:#dce9f3;padding:8px 16px;border-radius:24px;font-weight:700}}.FAIL,.INTERRUPTED{{background:#ffe0de;color:#8e2323}}.WARN{{background:#fff0c7;color:#684800}}.PASS{{background:#d5f4e4;color:#155d3c}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}}.card,section{{background:white;border:1px solid #d9e2eb;border-radius:12px;padding:24px;margin:16px 0}}.card strong{{display:block;font-size:30px;margin-top:10px}}.table-wrap{{overflow:auto;max-height:650px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #e5ebf0;vertical-align:top;overflow-wrap:anywhere}}th{{background:#edf3f8;position:sticky;top:0}}dl{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}dd{{margin:0;font-weight:600}}a{{display:inline-block;margin:6px 16px 6px 0;color:#175bab}}.path{{overflow-wrap:anywhere}}.empty{{color:#52677b}}
</style></head><body><header><div class="muted">LOCAL · VERIFIED · AUDITABLE</div><h1>Photo Archive Organizer</h1><div class="badge {summary['status']}">{summary['status']}</div>
<p>Command: {esc(state.command)} · Stage: {esc(state.stage)}</p><p class="path">Source: {esc(summary['source_root'])}<br>Destination: {esc(summary['destination_root'])}</p><p class="muted">{esc(state.started)} — {esc(state.ended)}</p></header>
<div class="cards">{cards}</div><section><h2>Reconciliation: {summary['reconciliation']}</h2><p>Primary media: {summary['primary_media_reconciliation']} · Associated sidecars: {summary['sidecar_reconciliation']}. Source eligible → planned → verified copies → independent destination recount. Path membership, sizes, and source stability must also agree.</p>{table(state.reconciliation.issues, ['path','reason','detail'])}</section>
<section><h2>Archive summary</h2><dl>{facts}</dl></section>
<section><h2>Free-space preflight</h2>{table([state.space] if state.space else [], ['status','planned_bytes','temporary_overhead','required_bytes','free_bytes'])}</section>
<section><h2>Timestamp quality</h2>{table([{'source':k,'files':v} for k,v in summary['timestamp_sources'].items()], ['source','files'])}</section>
<section id="not-archived"><h2>Source files not archived</h2><p>Every listed source file has an explicit exclusion, failure, or unconfirmed outcome. Verified files in _UNKNOWN_DATE are archived. Inventory coverage: {'COMPLETE' if state.inventory_complete else 'INCOMPLETE'}.</p>{table(missing, NOT_ARCHIVED_COLUMNS) if missing else '<p>No source files were left unarchived.</p>'}</section>
<section><h2>Inventory coverage gaps and skipped entries</h2>{table(coverage, ['path','reason'])}</section>
<section><h2>Warnings and errors</h2>{table(state.errors, ['path','stage','reason','detail'])}<ul>{''.join('<li>'+esc(w)+'</li>' for w in state.warnings)}</ul><p>{esc(state.fatal)}</p></section>
<section><h2>Year / month summary</h2>{table([{'month':k,'files':v} for k,v in sorted(months.items())], ['month','files'])}</section>
<section><h2>Daily grouping summary</h2>{table(daily, ['date','primary_media','sidecars','classification','destination'])}</section>
<section><h2>Audit files</h2>{anchors}</section></body></html>'''
        path.write_text(doc, encoding="utf-8")


class ReportWriter:
    def __init__(self, process):
        self.process = process

    def record_report_failure(self, config, state):
        """Best-effort correction: never leave a writable success summary after failure."""
        summary = summarize(config, state, build_not_archived(state))
        errors = []
        for path, content in [
            (self.process / "reports/summary.json", json.dumps(summary, ensure_ascii=False, indent=2)),
            (self.process / "reports/report.html", '<!doctype html><meta charset="utf-8"><title>Report failed</title>'
             '<h1>FAIL: report generation incomplete</h1><p>' + html.escape(state.fatal) + '</p>'
             '<p>Consult the execution log and copy journal. Exit code: ' + str(summary["exit_code"]) + '</p>'),
        ]:
            try:
                path.write_text(content, encoding="utf-8")
            except OSError as exc:
                errors.append(str(exc))
        try:
            with (self.process / "logs/photo_organizer.txt").open("a", encoding="utf-8") as stream:
                stream.write("\nFINAL STATUS CORRECTION: " + summary["status"] + "\n" + state.fatal + "\n")
        except OSError as exc:
            errors.append(str(exc))
        return summary, errors

    def write(self, config, state):
        missing = build_not_archived(state)
        summary = summarize(config, state, missing)
        coverage = state.inventory.gaps + state.inventory.skipped + state.reconciliation.source.gaps
        coverage += [{"path": i["path"], "reason": i["reason"] + ": " + i["detail"]} for i in state.reconciliation.issues if i["reason"] == "SOURCE_ADDED_AFTER_PLANNING"]
        reports, audit = self.process / "reports", self.process / "_AuditTrail"
        write_json(reports / "summary.json", summary)
        write_csv(reports / "not_archived.csv", missing, NOT_ARCHIVED_COLUMNS)
        write_csv(reports / "errors.csv", state.errors, ["path", "stage", "reason", "detail"])
        write_csv(reports / "ignored_files.csv", [{"source_relative_path": f.relative_path, "reason": f.reason, "detail": f.detail} for f in state.inventory.files if not f.eligible], ["source_relative_path", "reason", "detail"])
        write_csv(audit / "copy_verification.csv", [{**asdict(state.copies[p.media.relative_path]), "verification_status": "PASS" if state.copies[p.media.relative_path].success else "FAIL"} for p in state.plan if p.media.relative_path in state.copies],
                  ["source_relative_path", "destination_relative_path", "source_size", "destination_size", "source_sha256", "destination_sha256", "verification_status", "attempt_count", "reason", "error"])
        write_csv(audit / "reconciliation.csv", state.reconciliation.issues or [{"path": "", "reason": state.reconciliation.status, "detail": "independent inventory reconciliation"}], ["path", "reason", "detail"])
        write_json(audit / "source_inventory.json", state.inventory)
        with (self.process / "logs/photo_organizer.txt").open("a", encoding="utf-8") as stream:
            stream.write("\nFINAL SUMMARY\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            stream.write("\nSOURCE FILES NOT ARCHIVED\n")
            stream.write(f"Inventory coverage: {'COMPLETE' if state.inventory_complete else 'INCOMPLETE'}\nListed files: {len(missing)}\n")
            if not missing:
                stream.write("No source files were left unarchived.\n")
            for row in missing:
                stream.write("\n" + "\n".join(f"{k}: {v}" for k, v in row.items()) + "\n")
            stream.write("\nINVENTORY COVERAGE GAPS AND SKIPPED ENTRIES\n")
            for gap in coverage:
                stream.write(f"{gap['path']}: {gap['reason']}\n")
        HtmlReportWriter().write(reports / "report.html", summary, state, missing, coverage)
        return summary
