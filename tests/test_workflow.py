import csv
import hashlib
import json
from pathlib import Path, PureWindowsPath

import pytest

from photo_archive_organizer.application import ArchiveOrganizer
from photo_archive_organizer.copier import CopyEngine, publish_no_replace
from photo_archive_organizer.models import CopyResult
from conftest import FakeProvider, NOW, create_files


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob("*") if p.is_file()}


def load_report(dest):
    return json.loads((dest / "_process/reports/summary.json").read_text(encoding="utf-8"))


def missing_rows(dest):
    with (dest / "_process/reports/not_archived.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    # CSV cells use an apostrophe for spreadsheet safety; JSON/TXT preserve raw paths.
    for row in rows:
        for key, value in row.items():
            if value.startswith("'") and value[1:].lstrip().startswith(("=", "+", "-", "@")):
                row[key] = value[1:]
    return rows


def test_97_file_accounting_and_immutability(roots, make_config):
    source, dest = roots
    create_files(source, [f"{n:03}.JPG" for n in range(97)] + [f".trashed-{n}.jpg" for n in range(3)])
    before = snapshot(source)
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    assert app.execute("run") == 0
    report = load_report(dest)
    assert report["source_media_total"] == 100
    assert report["source_media_ignored"] == 3
    assert report["source_media_eligible"] == report["planned_media"] == report["successful_copies"] == report["destination_media_recount"] == 97
    assert report["reconciliation"] == "PASS"
    assert snapshot(source) == before
    assert len(missing_rows(dest)) == 3
    assert not list((dest / "_process/tmp").iterdir())
    txt = (dest / "_process/logs/photo_organizer.txt").read_text(encoding="utf-8")
    html = (dest / "_process/reports/report.html").read_text(encoding="utf-8")
    assert "SOURCE FILES NOT ARCHIVED" in txt
    assert "Source files not archived" in html


def test_deliberate_one_copy_failure(roots, make_config):
    source, dest = roots
    create_files(source, [f"{n:03}.JPG" for n in range(97)] + [f".trashed-{n}.jpg" for n in range(3)])
    class FailingEngine(CopyEngine):
        def copy_one(self, entry):
            if entry.media.path.name == "007.JPG":
                return CopyResult(entry.media.relative_path, entry.destination, attempt_count=3,
                                  reason="SOURCE_READ_FAILED", error="injected read failure", stage="SOURCE")
            return super().copy_one(entry)
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW, FailingEngine)
    assert app.execute("run") == 1
    report = load_report(dest)
    assert report["successful_copies"] == report["destination_media_recount"] == 96
    assert report["failed_copies"] == 1 and report["reconciliation"] == "FAIL"
    rows = {r["source_relative_path"]: r for r in missing_rows(dest)}
    assert rows["007.JPG"]["reason"] == "SOURCE_READ_FAILED"


@pytest.mark.parametrize("with_dates", [True, False])
def test_generic_filenames(roots, make_config, with_dates):
    source, dest = roots
    names = ["IMG_20180729_093414.jpg", "007.JPG", "Pasha4.jpg", "DSCN1277.JPG", "random name.BMP",
             "--------- ! 2021 travels 2025-12-07_000949.jpg", "--- Travels 2025-12-07_001202.jpg"]
    create_files(source, names)
    tags = {n: {"ExifIFD:DateTimeOriginal": "2002:03:04 05:06:07"} for n in names} if with_dates else {}
    provider = FakeProvider(tags)
    app = ArchiveOrganizer(make_config(), provider, NOW)
    assert app.execute("run") == 0
    assert {p.name for call in provider.calls for p in call} == set(names)
    assert app.summary["unknown_date_count"] == (0 if with_dates else 6)
    assert not missing_rows(dest)
    if with_dates:
        assert all((dest / "2002/03/Event01" / n).is_file() for n in names)
    else:
        assert (dest / "2018/07/_sparse/IMG_20180729_093414.jpg").exists()


def test_flist2_regression(roots, make_config):
    source, dest = roots
    listed = Path(__file__).parents[1] / "_refs/flist2.txt"
    names = []
    for line in listed.read_text().splitlines():
        path = PureWindowsPath(line)
        if path.suffix.lower() == ".jpg":
            names.append(path.name if path.parent.name == "NY_2024 Richmond" else "Life in America/" + path.name)
    assert len(names) == 54
    create_files(source, names)
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    before = snapshot(source)
    assert app.execute("run") == 0
    assert len(list((dest / "_UNKNOWN_DATE").iterdir())) == 44
    assert len(list((dest / "2024/02/Event01").iterdir())) == 10
    assert snapshot(source) == before


def test_ignored_directory_no_metadata_and_full_missing_report(roots, make_config):
    source, dest = roots
    create_files(source, ["ok.jpg", "@eaDir/a.JPG", "@eaDir/deep/info.bin", "notes.txt"])
    provider = FakeProvider()
    app = ArchiveOrganizer(make_config(), provider, NOW)
    assert app.execute("run") == 0
    assert [p.name for call in provider.calls for p in call] == ["ok.jpg"]
    rows = {r["source_relative_path"]: r for r in missing_rows(dest)}
    assert set(rows) == {"@eaDir/a.JPG", "@eaDir/deep/info.bin", "notes.txt"}
    assert rows["@eaDir/deep/info.bin"]["reason"] == "IGNORED_DIRECTORY_PATTERN"


@pytest.mark.parametrize("command", ["analyze", "plan"])
def test_preview_claims_destination_without_copy(roots, make_config, command):
    source, dest = roots
    create_files(source, ["007.JPG"])
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    assert app.execute(command) == 0
    assert load_report(dest)["reconciliation"] == "NOT_RUN"
    assert not (dest / "_UNKNOWN_DATE").exists()
    assert missing_rows(dest)[0]["reason"] == "ANALYSIS_ONLY"
    before = snapshot(dest)
    assert ArchiveOrganizer(make_config(), FakeProvider(), NOW).execute("run") == 2
    assert snapshot(dest) == before


def test_validate_leaves_no_artifacts(roots, make_config):
    assert ArchiveOrganizer(make_config(), FakeProvider(), NOW).execute("validate") == 0
    assert not roots[1].exists()


def test_collision_no_copy_and_explanation(roots, make_config):
    source, dest = roots
    create_files(source, ["a/007.JPG", "b/007.JPG", "other.jpg"])
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW)
    assert app.execute("run") == 2
    assert not (dest / "_UNKNOWN_DATE").exists()
    reasons = [r["reason"] for r in missing_rows(dest)]
    assert reasons.count("PLAN_COLLISION") == 2
    assert "NOT_ATTEMPTED_PREFLIGHT_FAILURE" in reasons


def test_metadata_error_still_copied_but_exit_failure(roots, make_config):
    source, dest = roots
    create_files(source, ["007.JPG"])
    provider = FakeProvider(errors={"007.JPG": "bad metadata"})
    app = ArchiveOrganizer(make_config(), provider, NOW)
    assert app.execute("run") == 1
    assert len(provider.calls) == 3
    assert load_report(dest)["reconciliation"] == "PASS"
    assert not missing_rows(dest)


def test_no_overwrite_publication(roots):
    source, _ = roots
    staged, final = source / "staged", source / "final"
    staged.write_bytes(b"new")
    final.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        publish_no_replace(staged, final)
    assert final.read_bytes() == b"old"


def test_transient_verification_retry(roots, make_config):
    source, dest = roots
    create_files(source, ["007.JPG"])
    from photo_archive_organizer.verifier import CopyVerifier
    class OnceBad(CopyVerifier):
        calls = 0
        def verify(self, *args):
            self.calls += 1
            if self.calls == 1:
                return False, 0, "bad"
            return super().verify(*args)
    def factory(*args):
        return CopyEngine(*args, verifier=OnceBad())
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW, factory)
    assert app.execute("run") == 0
    assert app.state.copies["007.JPG"].attempt_count == 2


def test_interrupted_writes_report(roots, make_config):
    source, dest = roots
    create_files(source, ["007.JPG"])
    class Interrupting(CopyEngine):
        def copy_one(self, entry):
            self.stop.set()
            return super().copy_one(entry)
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW, Interrupting)
    assert app.execute("run") == 3
    assert load_report(dest)["status"] == "INTERRUPTED"
    assert missing_rows(dest)[0]["reason"] == "INTERRUPTED"
    assert not list((dest / "_process/tmp").iterdir())


def test_same_count_wrong_files_fails(roots, make_config):
    source, dest = roots
    create_files(source, ["007.JPG"])
    class Substituting(CopyEngine):
        def run(self, *args):
            super().run(*args)
            (dest / "_UNKNOWN_DATE/007.JPG").rename(dest / "_UNKNOWN_DATE/wrong.JPG")
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW, Substituting)
    assert app.execute("run") == 1
    assert app.summary["destination_media_recount"] == app.summary["successful_copies"] == 1
    assert app.summary["reconciliation"] == "FAIL"
    assert missing_rows(dest)[0]["reason"] == "DESTINATION_MISSING"


def test_source_added_after_copy_fails(roots, make_config):
    source, dest = roots
    create_files(source, ["007.JPG"])
    class Adding(CopyEngine):
        def run(self, *args):
            super().run(*args)
            (source / "added.txt").write_bytes(b"external change")
    app = ArchiveOrganizer(make_config(), FakeProvider(), NOW, Adding)
    assert app.execute("run") == 1
    assert "SOURCE_ADDED_AFTER_PLANNING" in (dest / "_process/reports/report.html").read_text(encoding="utf-8")
