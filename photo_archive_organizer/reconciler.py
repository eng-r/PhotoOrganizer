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
            if (a.size, a.mtime_ns, a.identity, a.eligible) != (b.size, b.mtime_ns, b.identity, b.eligible):
                result.issues.append({"path": name, "reason": "SOURCE_CHANGED", "detail": "size/mtime/identity/eligibility changed"})
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
                        if path.suffix.lower() in self.config["include_extensions"]:
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
        good = sum(r.success for r in copies.values())
        count = len(initial.eligible)
        counts_match = count == len(result.source.eligible) == len(plan) == good == len(result.destination)
        if not counts_match or any(not r.success for r in copies.values()):
            result.issues.append({"path": "", "reason": "COUNT_MISMATCH", "detail": f"initial={count}; source={len(result.source.eligible)}; planned={len(plan)}; copied={good}; destination={len(result.destination)}"})
        result.complete = scan_complete and not result.source.gaps
        result.status = "PASS" if result.complete and not result.issues else "FAIL"
        return result
