import errno
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from photo_archive_organizer.application import ArchiveOrganizer
from photo_archive_organizer.copier import CopyEngine
from photo_archive_organizer.discovery import SourceScanner
from photo_archive_organizer.models import Inventory
from photo_archive_organizer.progress import ProgressReporter
from photo_archive_organizer.reporting import HtmlReportWriter, ReportWriter
from photo_archive_organizer.safety import PreflightValidator, SafetyError
from photo_archive_organizer.verifier import CopyVerifier
from conftest import FakeProvider, NOW, create_files
from test_workflow import load_report, missing_rows, snapshot


def test_insufficient_space_does_not_copy(roots, make_config, monkeypatch):
    from types import SimpleNamespace
    create_files(roots[0], ["007.JPG"])
    monkeypatch.setattr("photo_archive_organizer.safety.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    assert app.execute("run") == 2
    assert not (roots[1] / "_UNKNOWN_DATE").exists()
    assert missing_rows(roots[1])[0]["reason"] == "NOT_ATTEMPTED_PREFLIGHT_FAILURE"


def test_source_changed_between_analysis_and_copy(roots, make_config):
    create_files(roots[0], ["007.JPG"])
    class ChangingProvider(FakeProvider):
        def read_batch(self, paths):
            result = super().read_batch(paths)
            paths[0].write_bytes(b"externally changed after inventory")
            return result
    app = ArchiveOrganizer(make_config(), ChangingProvider(), NOW)
    assert app.execute("run") == 1
    assert app.state.copies["007.JPG"].reason == "SOURCE_CHANGED"
    assert not (roots[1] / "_UNKNOWN_DATE/007.JPG").exists()


def test_hash_failure_never_publishes(roots, make_config):
    create_files(roots[0], ["007.JPG"])
    class BadVerifier(CopyVerifier):
        def verify(self, *args):
            return False, 0, "bad"
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW,
                           lambda *args: CopyEngine(*args, verifier=BadVerifier()))
    assert app.execute("run") == 1
    result = app.state.copies["007.JPG"]
    assert result.attempt_count == 3 and result.reason == "VERIFICATION_FAILED"
    assert not (roots[1] / "_UNKNOWN_DATE/007.JPG").exists()
    assert not list((roots[1] / "_process/tmp").iterdir())


def test_publication_race_preserves_existing_file(roots, make_config):
    from photo_archive_organizer.copier import publish_no_replace
    create_files(roots[0], ["007.JPG"])
    def racing_publish(staged, final):
        final.write_bytes(b"another writer's file")
        publish_no_replace(staged, final)
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW,
                           lambda *args: CopyEngine(*args, publisher=racing_publish))
    assert app.execute("run") == 1
    assert (roots[1] / "_UNKNOWN_DATE/007.JPG").read_bytes() == b"another writer's file"
    row = missing_rows(roots[1])[0]
    assert row["reason"] == "PUBLICATION_FAILED" and row["destination_presence"] == "PRESENT_UNVERIFIED"


def test_disk_full_stops_new_scheduling(roots, make_config):
    create_files(roots[0], ["001.JPG", "002.JPG", "003.JPG"])
    def full_disk(*_):
        raise OSError(errno.ENOSPC, "disk full")
    cfg = make_config(copy={"copy_workers": 1, "retry_count": 0, "retry_delays_seconds": []})
    app = ArchiveOrganizer(cfg, FakeProvider(), NOW, lambda *args: CopyEngine(*args, publisher=full_disk))
    assert app.execute("run") == 1
    assert app.summary["successful_copies"] == 0
    assert app.summary["not_attempted_copies"] == 2


def test_report_failure_is_nonzero(roots, make_config, monkeypatch):
    create_files(roots[0], ["007.JPG"])
    def fail(*args):
        raise OSError("report disk lost")
    monkeypatch.setattr(HtmlReportWriter, "write", fail)
    assert ArchiveOrganizer(make_config(), FakeProvider(), NOW).execute("run") == 2
    assert load_report(roots[1])["exit_code"] == 2
    assert load_report(roots[1])["status"] == "FAIL"


def test_inventory_gap_explained(roots, make_config, monkeypatch):
    source, dest = roots
    create_files(source, ["ok.jpg", "blocked/a.jpg"])
    actual_scan = os.scandir
    def scan(path):
        if Path(path) == source / "blocked":
            raise PermissionError("blocked for test")
        return actual_scan(path)
    monkeypatch.setattr("photo_archive_organizer.discovery.os.scandir", scan)
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    assert app.execute("run") == 2
    report = load_report(dest)
    assert not report["inventory_complete"]
    assert "blocked for test" in (dest / "_process/reports/report.html").read_text(encoding="utf-8")
    assert not (dest / "_UNKNOWN_DATE").exists()


def test_progress_heartbeats_without_file_completion(tmp_path):
    path = tmp_path / "log.txt"
    progress = ProgressReporter(.02, path)
    progress.start()
    progress.set_stage("VERIFY", "large file")
    time.sleep(.09)
    progress.close()
    assert path.read_text().count("large file") >= 2


def test_unusual_names_escaped_in_html(roots, make_config):
    create_files(roots[0], ["007.JPG", "notes & facts.txt"])
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    assert app.execute("run") == 0
    html = (roots[1] / "_process/reports/report.html").read_text(encoding="utf-8")
    assert "notes &amp; facts.txt" in html
    for link in ["../logs/photo_organizer.txt", "not_archived.csv", "summary.json"]:
        assert f'href="{link}"' in html


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_junction_skipped_and_root_rejected(roots, make_config):
    source, _ = roots
    real = source / "real"
    real.mkdir()
    (real / "x.jpg").write_bytes(b"x")
    link = source / "junction"
    process = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real)], capture_output=True)
    if process.returncode:
        pytest.skip("junction creation unavailable on host")
    inv = SourceScanner(make_config().section("media")).scan(source)
    assert len(inv.eligible) == 1 and inv.skipped[0]["path"] == "junction"
    with pytest.raises(SafetyError):
        PreflightValidator().validate_paths(make_config(source_root=str(link)))


def test_large_streamed_copy_and_preserved_mtime(roots, make_config):
    source, dest = roots
    path = source / "large.mp4"
    with path.open("wb") as stream:
        for _ in range(9):
            stream.write(b"01234567" * (1024 * 128))
    before = snapshot(source)
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    assert app.execute("run") == 0
    copied = dest / "_UNKNOWN_DATE/large.mp4"
    assert copied.stat().st_mtime_ns == path.stat().st_mtime_ns
    assert app.summary["bytes_copied"] == 9 * 1024 * 1024
    assert snapshot(source) == before
