"""Filesystem safety and exclusive ownership; no source writes."""
import json
import math
import os
import shutil
import socket
import stat
import tempfile
from pathlib import Path

from . import __version__


class SafetyError(RuntimeError):
    pass


def is_link(path: Path) -> bool:
    st = path.lstat()
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def check_chain(path: Path):
    for part in reversed([path, *path.parents]):
        if os.path.lexists(part) and is_link(part):
            raise SafetyError(f"symlink/reparse path is not allowed: {part}")


def identity(st):
    return st.st_dev, st.st_ino


def same_file_state(media, st):
    return media.size == st.st_size and media.mtime_ns == st.st_mtime_ns and media.identity == identity(st)


def safe_name(name):
    stem = name.split(".")[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{p}{n}" for p in ("COM", "LPT") for n in "123456789¹²³"}
    return bool(name) and name not in (".", "..") and not name.endswith((".", " ")) and stem not in reserved and not any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)


class PreflightValidator:
    def validate_paths(self, config):
        source, destination = config.source_root, config.destination_root
        check_chain(source)
        check_chain(destination)
        s, d = str(source.resolve()).casefold(), str(destination.resolve()).casefold()
        try:
            common = os.path.commonpath([s, d])
        except ValueError:  # different volumes
            common = ""
        if common in (s, d):
            raise SafetyError("source and destination must not overlap")
        if not source.is_dir():
            raise SafetyError("source must be an existing directory")
        try:
            with os.scandir(source) as entries:
                next(entries, None)
        except OSError as exc:
            raise SafetyError(f"source is not readable: {exc}") from exc
        if destination.exists():
            if not destination.is_dir():
                raise SafetyError("destination is not a directory")
            if any(destination.iterdir()):
                raise SafetyError("destination is not empty")
        ancestor = destination
        while not ancestor.exists():
            ancestor = ancestor.parent
        try:
            fd, name = tempfile.mkstemp(prefix=".photo-organizer-probe-", dir=ancestor)
            os.close(fd)
            Path(name).unlink()
        except OSError as exc:
            raise SafetyError(f"destination is not writable: {exc}") from exc


class DestinationClaim:
    def __init__(self, destination, run_id, started):
        self.destination = destination
        self.process = destination / "_process"
        self.claim = self.process / ".archive_organizer_claim"
        self.record = {"run_id": run_id, "process_id": os.getpid(), "hostname": socket.gethostname(),
                       "start_time": started, "tool_version": __version__}
        self.owned = False
        self._identities = {}

    def acquire(self):
        check_chain(self.destination)
        self.destination.mkdir(parents=True, exist_ok=True)
        # The process container may have been created by another simultaneous claimant.
        # Only exclusive file creation elects the owner; a losing claimant never cleans up.
        entries = list(self.destination.iterdir())
        if any(p.name != "_process" for p in entries):
            raise SafetyError("destination is not empty")
        self.process.mkdir(exist_ok=True)
        check_chain(self.process)
        try:
            with self.claim.open("x", encoding="utf-8") as output:
                json.dump(self.record, output)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError as exc:
            raise SafetyError("destination already claimed by another invocation") from exc
        # A malicious/stale non-claim artifact is not ours. Leave it untouched.
        if any(p != self.claim for p in self.process.iterdir()):
            raise SafetyError("unexpected artifacts in process directory")
        self.owned = True
        for p in (self.destination, self.process, self.claim):
            self._identities[p] = identity(p.stat())
        for name in ("logs", "reports", "_AuditTrail", "tmp"):
            p = self.process / name
            p.mkdir()
            self._identities[p] = identity(p.stat())
        return self.process

    def assert_owned(self, before_copy=False):
        for p, expected in self._identities.items():
            check_chain(p)
            if identity(p.stat()) != expected:
                raise SafetyError(f"owned path changed: {p}")
        if json.loads(self.claim.read_text(encoding="utf-8")) != self.record:
            raise SafetyError("destination claim changed")
        if before_copy and any(p != self.process for p in self.destination.iterdir()):
            raise SafetyError("unexpected destination entries before copying")


class SpaceEstimator:
    def estimate(self, plan, destination, workers, margin):
        sizes = sorted((p.media.size for p in plan), reverse=True)
        total, overhead = sum(sizes), sum(sizes[:workers])
        required = math.ceil((total + overhead) * (1 + margin / 100))
        free = shutil.disk_usage(destination).free
        return {"planned_bytes": total, "temporary_overhead": overhead, "margin_percent": margin,
                "required_bytes": required, "free_bytes": free, "status": "PASS" if free >= required else "FAIL"}
