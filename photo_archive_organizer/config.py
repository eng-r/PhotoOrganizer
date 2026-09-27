import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


DEFAULTS = {
    "media": {
        "include_extensions": [".jpg", ".jpeg", ".heic", ".png", ".tif", ".tiff", ".bmp",
                               ".cr2", ".cr3", ".arw", ".dng", ".mp4", ".mov", ".m4v"],
        "ignore_name_patterns": [".trashed.*", ".trashed-*", "Thumbs.db", ".DS_Store"],
        "ignore_directory_patterns": ["@eaDir", ".Trash-*"],
    },
    "timestamp": {
        "priority": ["DateTimeOriginal", "XMPDateCreated", "CreateDate", "VideoCreationDate", "FilenameDate"],
        "minimum_year": 1980, "future_tolerance_days": 2,
    },
    "day_grouping": {"threshold": 15},
    "copy": {"retry_count": 2, "retry_delays_seconds": [1, 3], "copy_workers": 2, "free_space_margin_percent": 10},
    "runtime": {"progress_interval_seconds": 5, "metadata_timeout_seconds": 120},
}
CATEGORIES = DEFAULTS["timestamp"]["priority"] + ["FilesystemMTime"]


def _object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ConfigError(f"duplicate JSON key: {k}")
        result[k] = v
    return result


@dataclass(frozen=True)
class AppConfig:
    source_root: Path
    destination_root: Path
    data: dict

    def section(self, name):
        return self.data[name]


class ConfigLoader:
    def load(self, path: Path) -> AppConfig:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_object)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"cannot read configuration: {exc}") from exc
        return self.from_dict(data, path.absolute().parent)

    def from_dict(self, data: dict, base: Path | None = None) -> AppConfig:
        if not isinstance(data, dict):
            raise ConfigError("configuration must be an object")
        unknown = set(data) - set(DEFAULTS) - {"source_root", "destination_root"}
        if unknown:
            raise ConfigError(f"unknown configuration keys: {sorted(unknown)}")
        effective = copy.deepcopy(DEFAULTS)
        for group, defaults in DEFAULTS.items():
            supplied = data.get(group, {})
            if not isinstance(supplied, dict) or set(supplied) - set(defaults):
                raise ConfigError(f"invalid/unknown keys in {group}")
            effective[group].update(supplied)
        for name in ("source_root", "destination_root"):
            value = data.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"{name} must be a nonempty path")
            p = Path(value).expanduser()
            effective[name] = str((p if p.is_absolute() else (base or Path.cwd()) / p).absolute())
        self._validate(effective)
        effective["media"]["include_extensions"] = sorted(set(e.lower() for e in effective["media"]["include_extensions"]))
        return AppConfig(Path(effective["source_root"]), Path(effective["destination_root"]), effective)

    def _validate(self, d):
        for key, values in d["media"].items():
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ConfigError(f"media.{key} must be a list of nonempty strings")
        extensions = d["media"]["include_extensions"]
        if not extensions or any(not e.startswith(".") or len(e) < 2 or any(c in e for c in '/\\*?[]') for e in extensions):
            raise ConfigError("invalid media extensions")
        priority = d["timestamp"]["priority"]
        if not isinstance(priority, list) or any(not isinstance(p, str) or p not in CATEGORIES for p in priority):
            raise ConfigError("invalid timestamp priority")
        if len(set(priority)) != len(priority):
            raise ConfigError("duplicate timestamp category")
        ranks = [2 if p == "FilesystemMTime" else 1 if p == "FilenameDate" else 0 for p in priority]
        if ranks != sorted(ranks):
            raise ConfigError("embedded metadata must precede filename and filesystem fallbacks")
        integer_fields = {"timestamp": ["minimum_year"], "day_grouping": ["threshold"],
                          "copy": ["retry_count", "copy_workers"]}
        for section, keys in integer_fields.items():
            for key in keys:
                if type(d[section][key]) is not int:
                    raise ConfigError(f"{section}.{key} must be an integer")
        for section, keys in {"timestamp": ["minimum_year", "future_tolerance_days"],
                              "day_grouping": ["threshold"],
                              "copy": ["retry_count", "copy_workers", "free_space_margin_percent"],
                              "runtime": list(d["runtime"])}.items():
            for key in keys:
                n = d[section][key]
                if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0:
                    raise ConfigError(f"{section}.{key} must be finite and nonnegative")
        if not 1 <= d["timestamp"]["minimum_year"] <= 9999:
            raise ConfigError("minimum_year must be 1..9999")
        if d["day_grouping"]["threshold"] < 1:
            raise ConfigError("day_grouping.threshold must be at least 1")
        if d["copy"]["copy_workers"] < 1 or any(v <= 0 for v in d["runtime"].values()):
            raise ConfigError("workers and runtime intervals must be positive")
        delays = d["copy"]["retry_delays_seconds"]
        if not isinstance(delays, list) or len(delays) != d["copy"]["retry_count"]:
            raise ConfigError("retry delays must match retry_count")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in delays):
            raise ConfigError("retry delays must be finite and nonnegative")
