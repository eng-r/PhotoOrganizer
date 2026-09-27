from datetime import datetime, timedelta

import pytest

from photo_archive_organizer.discovery import SourceScanner
from photo_archive_organizer.event_grouper import EventGrouper
from photo_archive_organizer.models import MediaMetadata, ResolvedTimestamp
from photo_archive_organizer.planner import ArchivePlanner
from photo_archive_organizer.safety import SpaceEstimator
from photo_archive_organizer.timestamp_resolver import TimestampResolver, filename_date
from conftest import NOW, create_files


@pytest.mark.parametrize("name,expected", [
    ("IMG_20180729_093414.jpg", "2018-07-29T09:34:14"),
    ("IMG_20260927_142355.jpg", "2026-09-27T14:23:55"),
    ("PXL_20260927_142355123.jpg", "2026-09-27T14:23:55.123000"),
    ("VID_20260927_142355.mp4", "2026-09-27T14:23:55"),
    ("2026-09-27 14.23.55.jpg", "2026-09-27T14:23:55"),
    ("IMG-20260927-WA0001.jpg", "2026-09-27T00:00:00"),
    ("Screenshot_20260927-142355.png", "2026-09-27T14:23:55"),
    ("IMG20240518125418_01.jpg", "2024-05-18T12:54:18"),
    ("VID20251225164957.mp4", "2025-12-25T16:49:57"),
    ("2024-02-03_002850.jpg", "2024-02-03T00:28:50"),
])
def test_filename_formats(name, expected):
    value, _ = filename_date(name)
    assert value.isoformat() == expected


@pytest.mark.parametrize("name", ["007.JPG", "Pasha4.jpg", "DSCN1277.JPG", "random name.BMP", "DSC01234.JPG", "MVI_4567.MP4", "--------- ! 2021 travels 2025-12-07_000949.jpg", "--- Travels 2025-12-07_001202.jpg", "2024-02-03_002850_extra.jpg"])
def test_random_names_are_not_dates(name):
    assert filename_date(name)[0] is None


@pytest.mark.parametrize("name", ["2024-02-30_002850.jpg", "IMG_20241301_093414.jpg", "2024-02-03_256000.jpg"])
def test_invalid_calendar(name):
    with pytest.raises(ValueError):
        filename_date(name)


def test_metadata_priority_and_provenance(roots, make_config):
    source, _ = roots
    create_files(source, ["IMG_20180729_093414.jpg"])
    media = SourceScanner(make_config().section("media")).scan(source).eligible[0]
    resolver = TimestampResolver(make_config().section("timestamp"), NOW)
    result = resolver.resolve(media, MediaMetadata({"ExifIFD:DateTimeOriginal": "2001:02:03 04:05:06", "ExifIFD:OffsetTimeOriginal": "+03:00"}))
    assert result.value.year == 2001 and result.timezone_known
    assert result.source_field == "ExifIFD:DateTimeOriginal"
    fallback = resolver.resolve(media, MediaMetadata({"ExifIFD:DateTimeOriginal": "1900:02:03 04:05:06"}))
    assert fallback.category == "FilenameDate" and fallback.rejected_candidates


def test_unknown_and_opt_in_mtime(roots, make_config):
    source, _ = roots
    create_files(source, ["007.JPG"])
    media = SourceScanner(make_config().section("media")).scan(source).eligible[0]
    assert TimestampResolver(make_config().section("timestamp"), NOW).resolve(media, MediaMetadata()).value is None
    cfg = make_config(timestamp={"priority": ["FilesystemMTime"]})
    result = TimestampResolver(cfg.section("timestamp"), datetime(2090, 1, 1)).resolve(media, MediaMetadata())
    assert result.category == "FilesystemMTime" and result.confidence == "LOW"


@pytest.mark.parametrize("length,events", [(1, 1), (2, 1), (3, 1), (4, 2), (6, 2), (7, 3)])
def test_dense_runs(make_config, length, events):
    decisions = [ResolvedTimestamp(datetime(2024, 7, 1) + timedelta(days=i)) for i in range(length) for _ in range(4)]
    grouped = EventGrouper(make_config().section("event_grouping")).group(decisions)
    assert len({e for _, e in grouped.values()}) == events


def test_sparse_gaps_and_boundaries(make_config):
    values = [(datetime(2023, 12, 31), 4), (datetime(2024, 1, 1), 4), (datetime(2024, 1, 2), 3), (datetime(2024, 1, 3), 4), (datetime(2024, 1, 8), 4)]
    mapping = EventGrouper(make_config().section("event_grouping")).group([ResolvedTimestamp(d) for d, count in values for _ in range(count)])
    assert [mapping[d.date()][1] for d, _ in values] == ["Event01", "Event01", "", "Event02", "Event03"]


def test_collision_and_determinism(roots, make_config):
    source, _ = roots
    create_files(source, ["a/007.JPG", "b/007.JPG", "other.bmp"])
    cfg = make_config()
    files = SourceScanner(cfg.section("media")).scan(source).eligible
    dates = {f.relative_path: ResolvedTimestamp() for f in files}
    planner = ArchivePlanner(cfg.section("event_grouping"))
    plan = planner.build(files, dates)
    assert plan == planner.build(list(reversed(files)), dates)
    assert planner.validate(plan, files) == {"a/007.JPG", "b/007.JPG"}


def test_space_margin(roots, make_config, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("photo_archive_organizer.safety.shutil.disk_usage", lambda p: SimpleNamespace(free=330))
    plans = [SimpleNamespace(media=SimpleNamespace(size=100)) for _ in range(2)]
    result = SpaceEstimator().estimate(plans, roots[1], 1, 10)
    assert result["required_bytes"] == 330 and result["status"] == "PASS"
