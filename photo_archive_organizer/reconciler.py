import os
import stat

from .discovery import SourceScanner
from .models import ReconciliationResult
from .safety import check_chain, is_link


class ArchiveReconciler:
    def __init__(self, media_config, progress=None, stop=None):
        self.config, self.progress, self.stop = media_config, progress, stop

    def reconcile(self, source, destination, initial, plan, copies):
        result = ReconciliationResult()
        result.source = SourceScanner(self.config, self.progress, self.stop).scan(source)
        result.issues.extend({"path": g["path"], "reason": "SOURCE_INVENTORY_INCOMPLETE", "detail": g["reason"]} for g in result.source.gaps)
        before = {f.relative_path: f for f in initial.files}
        after = {f.relative_path: f for f in result.source.files}
        for name in sorted(before.keys() - after.keys()):
            result.issues.append({"path": name, "reason": "SOURCE_DISAPPEARED", "detail": "present initially, absent at recount"})
        for name in sorted(after.keys() - before.keys()):
            result.issues.append({"path": name, "reason": "SOURCE_ADDED_AFTER_PLANNING", "detail": "absent from initial inventory"})
        for name in sorted(before.keys() & after.keys()):
            a, b = before[name], after[name]
            if (a.size, a.mtime_ns, a.identity, a.eligible, a.media_role, a.associated_primary) != (b.size, b.mtime_ns, b.identity, b.eligible, b.media_role, b.associated_primary):
                result.issues.append({"path": name, "reason": "SOURCE_CHANGED", "detail": "size/mtime/identity/role/association changed"})
        if initial.skipped != result.source.skipped:
            result.issues.append({"path": "", "reason": "SOURCE_CHANGED", "detail": "skipped link/special-entry inventory changed"})
        expected = {p.destination: p for p in plan}
        stack = [destination]
        actual_all = {}
        scan_complete = True
        while stack:
            if self.stop and self.stop.is_set():
                raise InterruptedError("reconciliation interrupted")
            directory = stack.pop()
            try:
                check_chain(directory)
                with os.scandir(directory) as scan:
                    entries = sorted(scan, key=lambda e: e.name)
                for entry in entries:
                    if directory == destination and entry.name == "_process":
                        continue
                    path = directory / entry.name
                    relative = path.relative_to(destination).as_posix()
                    if is_link(path):
                        result.issues.append({"path": relative, "reason": "UNEXPECTED_DESTINATION_LINK", "detail": "not followed"})
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(path)
                    elif stat.S_ISREG(st.st_mode):
                        actual_all[relative] = st.st_size
                        result.destination[relative] = st.st_size
                    else:
                        result.issues.append({"path": relative, "reason": "UNEXPECTED_DESTINATION_ENTRY", "detail": "not a regular file"})
            except (OSError, RuntimeError) as exc:
                scan_complete = False
                result.issues.append({"path": str(directory), "reason": "DESTINATION_SCAN_FAILED", "detail": str(exc)})
        for name, entry in expected.items():
            if name not in actual_all:
                result.issues.append({"path": entry.media.relative_path, "reason": "DESTINATION_MISSING", "detail": name})
            elif actual_all[name] != entry.media.size:
                result.issues.append({"path": entry.media.relative_path, "reason": "DESTINATION_MISMATCH", "detail": name})
        for name in sorted(actual_all.keys() - expected.keys()):
            result.issues.append({"path": name, "reason": "UNEXPECTED_DESTINATION_FILE", "detail": "not in plan"})
        primary_plan = [p for p in plan if p.media_role == "PRIMARY_MEDIA"]
        sidecar_plan = [p for p in plan if p.media_role == "SIDECAR"]
        result.primary_destination = {p.destination: result.destination[p.destination] for p in primary_plan if p.destination in result.destination}
        result.sidecar_destination = {p.destination: result.destination[p.destination] for p in sidecar_plan if p.destination in result.destination}
        primary_good = sum(copies.get(p.media.relative_path) is not None and copies[p.media.relative_path].success for p in primary_plan)
        sidecar_good = sum(copies.get(p.media.relative_path) is not None and copies[p.media.relative_path].success for p in sidecar_plan)
        primary_counts = (len(initial.primary_media), len(result.source.primary_media), len(primary_plan), primary_good, len(result.primary_destination))
        sidecar_counts = (len(initial.associated_sidecars), len(result.source.associated_sidecars), len(sidecar_plan), sidecar_good, len(result.sidecar_destination))
        primary_ok = len(set(primary_counts)) == 1 and all(copies[p.media.relative_path].success for p in primary_plan)
        sidecar_ok = len(set(sidecar_counts)) == 1 and all(copies[p.media.relative_path].success for p in sidecar_plan)
        if not primary_ok:
            result.issues.append({"path": "", "reason": "PRIMARY_MEDIA_COUNT_MISMATCH", "detail": "initial=%d; source=%d; planned=%d; copied=%d; destination=%d" % primary_counts})
        if not sidecar_ok:
            result.issues.append({"path": "", "reason": "SIDECAR_COUNT_MISMATCH", "detail": "initial=%d; source=%d; planned=%d; copied=%d; destination=%d" % sidecar_counts})
        result.complete = scan_complete and not result.source.gaps
        primary_paths = {p.media.relative_path for p in primary_plan}
        sidecar_paths = {p.media.relative_path for p in sidecar_plan}
        global_reasons = {"SOURCE_INVENTORY_INCOMPLETE", "SOURCE_ADDED_AFTER_PLANNING", "SOURCE_CHANGED",
                          "UNEXPECTED_DESTINATION_LINK", "UNEXPECTED_DESTINATION_ENTRY", "DESTINATION_SCAN_FAILED",
                          "UNEXPECTED_DESTINATION_FILE"}
        primary_issues = any(i["reason"] == "PRIMARY_MEDIA_COUNT_MISMATCH" or i["path"] in primary_paths or i["reason"] in global_reasons for i in result.issues)
        sidecar_issues = any(i["reason"] == "SIDECAR_COUNT_MISMATCH" or i["path"] in sidecar_paths or i["reason"] in global_reasons for i in result.issues)
        result.primary_status = "PASS" if result.complete and primary_ok and not primary_issues else "FAIL"
        result.sidecar_status = "PASS" if result.complete and sidecar_ok and not sidecar_issues else "FAIL"
        result.status = "PASS" if result.complete and not result.issues else "FAIL"
        return result
