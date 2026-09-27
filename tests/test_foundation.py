import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from photo_archive_organizer.config import ConfigError, ConfigLoader
from photo_archive_organizer.discovery import SourceScanner
from photo_archive_organizer.safety import DestinationClaim, PreflightValidator, SafetyError
from conftest import create_files


@pytest.mark.parametrize("section", [
    {"timestamp": {"allow_filename_fallback": True}}, {"copy": {"verify": "size_and_sha256"}},
    {"copy": {"collision_policy": "fail"}}, {"copy": {"copy_workers": True}},
    {"timestamp": {"priority": ["FilenameDate", "DateTimeOriginal"]}},
    {"timestamp": {"priority": ["FilesystemMTime", "FilenameDate"]}},
    {"timestamp": {"priority": ["CreateDate", "CreateDate"]}},
    {"day_grouping": {"threshold": 0}}, {"day_grouping": {"threshold": 1.5}},
    {"runtime": {"progress_interval_seconds": 0}},
    {"copy": {"free_space_margin_percent": float('nan')}},
    {"copy": {"retry_count": 3}}, {"timestamp": {"priority": ["Canon"]}},
])
def test_invalid_config(make_config, section):
    with pytest.raises(ConfigError):
        make_config(**section)


def test_priority_authoritative(make_config):
    cfg = make_config(timestamp={"priority": []})
    assert cfg.section("timestamp")["priority"] == []
    assert "FilesystemMTime" not in make_config().section("timestamp")["priority"]
    assert ".bmp" in cfg.section("media")["include_extensions"]


def test_duplicate_json_and_relative_paths(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"source_root":"a", "source_root":"b"}')
    with pytest.raises(ConfigError):
        ConfigLoader().load(path)
    path.write_text(json.dumps({"source_root": "a", "destination_root": "b"}))
    cfg = ConfigLoader().load(path)
    assert cfg.source_root == tmp_path / "a"


@pytest.mark.parametrize("kind", ["same", "inside", "parent", "nonempty"])
def test_unsafe_destination(roots, make_config, kind):
    source, dest = roots
    if kind == "same":
        dest = source
    elif kind == "inside":
        dest = source / "archive"
    elif kind == "parent":
        dest = source.parent
    else:
        dest.mkdir()
        (dest / "_process").mkdir()
    cfg = make_config(destination_root=str(dest))
    with pytest.raises(SafetyError):
        PreflightValidator().validate_paths(cfg)


def test_claim_elects_one_owner(roots):
    source, dest = roots
    gate = threading.Barrier(2)
    def attempt(i):
        claim = DestinationClaim(dest, str(i), "2026-09-27")
        gate.wait()
        try:
            claim.acquire()
            return claim
        except (SafetyError, FileExistsError):
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    winners = [r for r in results if r]
    assert len(winners) == 1
    winner = winners[0]
    winner.assert_owned(before_copy=True)
    record = json.loads(winner.claim.read_text())
    assert set(record) == {"run_id", "process_id", "hostname", "start_time", "tool_version"}
    with pytest.raises(SafetyError):
        DestinationClaim(dest, "other", "later").acquire()
    assert json.loads(winner.claim.read_text()) == record


def test_ignored_descendants_are_all_inventoried(roots, make_config):
    source, _ = roots
    create_files(source, ["photo.JPG", "random.BMP", ".trashed-123-x.jpg", "notes.txt", "@eaDir/one.jpg", "@eaDir/deep/two.bin"])
    inv = SourceScanner(make_config().section("media")).scan(source)
    assert len(inv.files) == 6
    assert len(inv.eligible) == 2
    assert all(f.reason == "IGNORED_DIRECTORY_PATTERN" for f in inv.files if f.relative_path.startswith("@eaDir/"))
    assert not inv.gaps


def test_link_not_followed(roots, make_config):
    source, _ = roots
    (source / "real").mkdir()
    (source / "real/x.jpg").write_bytes(b"x")
    try:
        (source / "link").symlink_to(source / "real", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted by host")
    inv = SourceScanner(make_config().section("media")).scan(source)
    assert len(inv.eligible) == 1
    assert inv.skipped[0]["path"] == "link"
