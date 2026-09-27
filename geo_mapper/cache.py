import json
from pathlib import Path

from .config import CACHE_SCHEMA_VERSION


class EnrichmentCache:
    def __init__(self, path: Path):
        self.path = path
        self.records = {}
        self.warnings = []

    def load(self):
        if not self.path.is_file():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != CACHE_SCHEMA_VERSION or not isinstance(data.get("records"), dict):
                raise ValueError("unsupported cache schema")
            self.records = data["records"]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.warnings.append(f"cache ignored: {exc}")
            self.records = {}
        return self

    @staticmethod
    def key(provider, latitude, longitude):
        return f"{provider}:{latitude:.4f}:{longitude:.4f}:v{CACHE_SCHEMA_VERSION}"

    def get(self, provider, latitude, longitude):
        value = self.records.get(self.key(provider, latitude, longitude))
        return value if isinstance(value, dict) and value.get("place_name") else None

    def put(self, provider, latitude, longitude, value):
        self.records[self.key(provider, latitude, longitude)] = value

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps({"schema_version": CACHE_SCHEMA_VERSION, "records": self.records}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.path)
