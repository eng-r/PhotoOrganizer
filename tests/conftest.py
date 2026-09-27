import copy
from datetime import datetime, timezone

import pytest

from photo_archive_organizer.config import ConfigLoader
from photo_archive_organizer.metadata import MetadataProvider
from photo_archive_organizer.models import MediaMetadata


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


class FakeProvider(MetadataProvider):
    def __init__(self, tags=None, errors=None):
        self.tags = tags or {}
        self.errors = errors or {}
        self.calls = []

    def check(self):
        return "fake-1"

    def read_batch(self, paths):
        self.calls.append(list(paths))
        return {p: MediaMetadata(copy.deepcopy(self.tags.get(p.name, {})), self.errors.get(p.name, "")) for p in paths}


@pytest.fixture
def roots(tmp_path):
    source = tmp_path / "Source with spaces"
    source.mkdir()
    return source, tmp_path / "Archive"


@pytest.fixture
def make_config(roots):
    def make(**sections):
        source, destination = roots
        data = {"source_root": str(source), "destination_root": str(destination),
                "copy": {"retry_count": 2, "retry_delays_seconds": [0, 0]}}
        data.update(sections)
        return ConfigLoader().from_dict(data)
    return make


def create_files(source, names):
    for index, name in enumerate(names):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic file {index}: {name}".encode())
