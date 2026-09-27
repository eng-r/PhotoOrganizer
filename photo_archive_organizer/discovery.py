import fnmatch
import os
import stat

from .models import Inventory, MediaFile
from .safety import identity, is_link


class SourceScanner:
    def __init__(self, media_config, progress=None, stop=None):
        self.config, self.progress, self.stop = media_config, progress, stop

    @staticmethod
    def match(name, patterns):
        return next((p for p in patterns if fnmatch.fnmatchcase(name.casefold(), p.casefold())), "")

    def scan(self, root, inventory=None):
        result = inventory if inventory is not None else Inventory()
        stack = [(root, "")]
        while stack:
            if self.stop and self.stop.is_set():
                raise InterruptedError("source discovery interrupted")
            directory, inherited_rule = stack.pop()
            try:
                if is_link(directory):
                    result.skipped.append({"path": str(directory.relative_to(root)), "reason": "SKIPPED_REPARSE_POINT"})
                    continue
                with os.scandir(directory) as scan:
                    entries = sorted(scan, key=lambda e: (e.name.casefold(), e.name))
                for entry in entries:
                    path = directory / entry.name
                    relative = path.relative_to(root).as_posix()
                    try:
                        if is_link(path):
                            result.skipped.append({"path": relative, "reason": "SKIPPED_REPARSE_POINT"})
                            continue
                        # Windows DirEntry.stat may report zero file identity fields.
                        # A fresh path stat agrees with fstat during verified copying.
                        st = path.stat(follow_symlinks=False)
                        if stat.S_ISDIR(st.st_mode):
                            rule = inherited_rule or self.match(entry.name, self.config["ignore_directory_patterns"])
                            stack.append((path, rule))
                        elif stat.S_ISREG(st.st_mode):
                            recognized = path.suffix.lower() in self.config["include_extensions"]
                            name_rule = self.match(entry.name, self.config["ignore_name_patterns"])
                            reason, detail = "", ""
                            if inherited_rule:
                                reason, detail = "IGNORED_DIRECTORY_PATTERN", f"matched directory rule {inherited_rule}"
                            elif name_rule:
                                reason, detail = "IGNORED_NAME_PATTERN", f"matched name rule {name_rule}"
                            elif not recognized:
                                reason, detail = "UNSUPPORTED_EXTENSION", f"extension {path.suffix or '(none)'} is not configured media"
                            result.files.append(MediaFile(path, relative, st.st_size, st.st_mtime_ns, identity(st),
                                                          recognized, recognized and not reason, reason, detail, st.st_ctime_ns))
                        else:
                            result.skipped.append({"path": relative, "reason": "NOT_REGULAR_FILE"})
                    except OSError as exc:
                        result.gaps.append({"path": relative, "reason": str(exc)})
                if self.progress:
                    self.progress.update(f"{len(result.files)} files inventoried")
            except OSError as exc:
                result.gaps.append({"path": directory.relative_to(root).as_posix(), "reason": str(exc)})
        result.files.sort(key=lambda f: (f.relative_path.casefold(), f.relative_path))
        return result
