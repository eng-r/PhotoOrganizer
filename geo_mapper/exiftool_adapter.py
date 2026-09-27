import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .config import EXIFTOOL_BATCH_SIZE, EXIFTOOL_TIMEOUT_SECONDS


LOGGER = logging.getLogger(__name__)


class ExifToolError(RuntimeError):
    pass


class ExifToolAdapter:
    TAGS = (
        "SourceFile", "FileName", "Directory", "FileType", "DateTimeOriginal", "CreateDate",
        "ModifyDate", "OffsetTimeOriginal", "SubSecTimeOriginal", "GPSLatitude", "GPSLongitude",
        "GPSAltitude", "GPSDateTime", "Make", "Model",
    )

    def __init__(self, command=None, timeout=EXIFTOOL_TIMEOUT_SECONDS, batch_size=EXIFTOOL_BATCH_SIZE):
        configured = command or os.environ.get("GEO_MAPPER_EXIFTOOL", "exiftool")
        self.command = [configured] if isinstance(configured, str) else list(configured)
        self.timeout = timeout
        self.batch_size = batch_size

    def check(self):
        if not shutil.which(self.command[0]):
            raise ExifToolError("ExifTool was not found. Install ExifTool or configure GEO_MAPPER_EXIFTOOL. No source files were modified.")
        try:
            result = subprocess.run([*self.command, "-ver"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExifToolError(f"ExifTool is unavailable: {exc}. No source files were modified.") from exc
        if result.returncode or not result.stdout.strip():
            raise ExifToolError(f"ExifTool is unavailable: {result.stderr.strip()}. No source files were modified.")
        LOGGER.debug("ExifTool version %s", result.stdout.strip())
        return result.stdout.strip()

    def extract(self, paths):
        records = {}
        paths = list(paths)
        for start in range(0, len(paths), self.batch_size):
            batch = paths[start:start + self.batch_size]
            LOGGER.debug("Extracting mapper metadata for batch of %d files", len(batch))
            if any("\n" in str(p) or "\r" in str(p) for p in batch):
                raise ExifToolError("media paths containing newlines are unsupported")
            args = [*self.command, "-json", "-n", "-G1", "-s", "-charset", "filename=UTF8"]
            args.extend(f"-{tag}" for tag in self.TAGS)
            args.extend(["-@", "-"])
            try:
                input_text = "\n".join(str(path.resolve()) for path in batch) + "\n"
                result = subprocess.run(args, input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                        timeout=self.timeout, check=False)
                rows = json.loads(result.stdout)
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                raise ExifToolError(f"ExifTool metadata extraction failed: {exc}") from exc
            if not isinstance(rows, list):
                raise ExifToolError("ExifTool did not return a JSON array")
            for row in rows:
                source = row.get("SourceFile") or row.get("File:SourceFile")
                if source:
                    records[os.path.normcase(os.path.abspath(source))] = row
            if result.returncode and not rows:
                raise ExifToolError(f"ExifTool could not process the batch: {result.stderr.strip()}")
        return {path: records.get(os.path.normcase(os.path.abspath(path)), {"SourceFile": str(path), "Error": "ExifTool omitted file"})
                for path in paths}
