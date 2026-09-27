import json
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod

from .models import MediaMetadata
from .safety import SafetyError


class MetadataProvider(ABC):
    @abstractmethod
    def check(self) -> str:
        """Validate tooling and return version."""

    @abstractmethod
    def read_batch(self, paths) -> dict:
        """Return path -> MediaMetadata, including per-file failures."""


class ExifToolMetadataProvider(MetadataProvider):
    def __init__(self, timeout=120, command=None, stop=None):
        self.timeout, self.stop = timeout, stop
        self.command = command or [os.environ.get("PHOTO_ORGANIZER_EXIFTOOL", "exiftool")]

    def _execute(self, args, input_text=None):
        process = subprocess.Popen([*self.command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        started = time.monotonic()
        first = True
        try:
            while True:
                if self.stop and self.stop.is_set():
                    raise InterruptedError("metadata extraction interrupted")
                if time.monotonic() - started >= self.timeout:
                    raise TimeoutError("ExifTool request timed out")
                try:
                    out, err = process.communicate(input=input_text if first else None, timeout=min(.25, self.timeout))
                    return process.returncode, out, err
                except subprocess.TimeoutExpired:
                    first = False
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def check(self):
        if not shutil.which(self.command[0]):
            raise SafetyError("required ExifTool executable is unavailable")
        try:
            code, out, err = self._execute(["-ver"])
        except (OSError, TimeoutError) as exc:
            raise SafetyError(f"ExifTool unavailable: {exc}") from exc
        if code or not out.strip():
            raise SafetyError(f"ExifTool unavailable: {err}")
        return out.strip()

    def read_batch(self, paths):
        if not paths:
            return {}
        # Paths are absolute and line-delimited, so spaces and leading-hyphen basenames are safe.
        if any("\n" in str(p) or "\r" in str(p) for p in paths):
            return {p: MediaMetadata(error="newline in metadata path is unsupported") for p in paths}
        try:
            code, out, err = self._execute(
                ["-json", "-G1", "-a", "-s", "-charset", "filename=UTF8", "-api", "QuickTimeUTC=0",
                 "-time:all", "-Error", "-Warning", "-@", "-"],
                "\n".join(str(p.absolute()) for p in paths) + "\n")
            rows = json.loads(out)
            if not isinstance(rows, list):
                raise ValueError("ExifTool did not return an array")
            indexed = {os.path.normcase(os.path.abspath(r["SourceFile"])): r for r in rows if "SourceFile" in r}
            result = {}
            for p in paths:
                row = indexed.get(os.path.normcase(os.path.abspath(p)))
                if row is None:
                    result[p] = MediaMetadata(error=err.strip() or f"ExifTool omitted file (exit {code})")
                else:
                    errors = [str(v) for k, v in row.items() if k.split(":")[-1] == "Error"]
                    result[p] = MediaMetadata(row, "; ".join(errors))
            return result
        except (OSError, ValueError, TimeoutError) as exc:
            return {p: MediaMetadata(error=str(exc)) for p in paths}
