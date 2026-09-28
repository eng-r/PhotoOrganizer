from datetime import datetime
from types import SimpleNamespace

import pytest

from photo_archive_organizer.discovery import SourceScanner
from photo_archive_organizer.day_classifier import DayClassifier
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


def test_h264_date_time_original_is_m2ts_only(roots, make_config):
    source, _ = roots
    create_files(source, ["clip.m2ts", "clip.mp4"])
    media = {item.path.suffix: item for item in SourceScanner(make_config().section("media")).scan(source).eligible}
    resolver = TimestampResolver(make_config().section("timestamp"), NOW)
    metadata = MediaMetadata({"H264:DateTimeOriginal": "2017:05:31 18:07:34-05:00 DST"})

    m2ts = resolver.resolve(media[".m2ts"], metadata)
    assert m2ts.value.isoformat() == "2017-05-31T18:07:34-05:00"
    assert m2ts.category == "DateTimeOriginal"
    assert m2ts.source_field == "H264:DateTimeOriginal"
    assert m2ts.raw_candidates[0]["raw"].endswith(" DST")
    assert m2ts.raw_candidates[0]["interpreted_raw"].endswith("-05:00")

    assert resolver.resolve(media[".mp4"], metadata).value is None


def test_unknown_and_opt_in_mtime(roots, make_config):
    source, _ = roots
    create_files(source, ["007.JPG"])
    media = SourceScanner(make_config().section("media")).scan(source).eligible[0]
    assert TimestampResolver(make_config().section("timestamp"), NOW).resolve(media, MediaMetadata()).value is None
    cfg = make_config(timestamp={"priority": ["FilesystemMTime"]})
    result = TimestampResolver(cfg.section("timestamp"), datetime(2090, 1, 1)).resolve(media, MediaMetadata())
    assert result.category == "FilesystemMTime" and result.confidence == "LOW"


@pytest.mark.parametrize("count,expected", [(1, "SPARSE"), (14, "SPARSE"), (15, "DAY_FOLDER"), (16, "DAY_FOLDER")])
def test_daily_threshold_boundaries(count, expected):
    media = [SimpleNamespace(relative_path=str(i)) for i in range(count)]
    timestamps = {str(i): ResolvedTimestamp(datetime(2026, 9, 27)) for i in range(count)}
    result = DayClassifier({"threshold": 15}).classify(media, timestamps)
    assert result[datetime(2026, 9, 27).date()] == (expected, count)


def plan_for_dates(source, make_config, dated_names, threshold=15):
    create_files(source, [name for name, _ in dated_names])
    cfg = make_config(day_grouping={"threshold": threshold})
    inventory = SourceScanner(cfg.section("media")).scan(source)
    timestamps = {f.relative_path: ResolvedTimestamp(value) for f in inventory.primary_media
                  for name, value in dated_names if f.relative_path == name}
    return inventory, ArchivePlanner(cfg.section("day_grouping")).build(inventory.eligible, timestamps)


def test_sparse_only_month(roots, make_config):
    source, _ = roots
    dated = [(f"d02-{i}.jpg", datetime(2026, 4, 2)) for i in range(3)]
    dated += [(f"d09-{i}.jpg", datetime(2026, 4, 9)) for i in range(8)]
    dated += [(f"d21-{i}.jpg", datetime(2026, 4, 21)) for i in range(14)]
    _, plan = plan_for_dates(source, make_config, dated)
    assert len(plan) == 25
    assert {p.destination.split("/")[2] for p in plan} == {"_sparse"}
    assert {p.month_folder for p in plan} == {"04-Apr"}


def test_day_only_and_mixed_months(roots, make_config):
    source, _ = roots
    dated = [(f"may04-{i}.jpg", datetime(2026, 5, 4)) for i in range(15)]
    dated += [(f"may17-{i}.jpg", datetime(2026, 5, 17)) for i in range(20)]
    _, plan = plan_for_dates(source, make_config, dated)
    assert {p.day_folder for p in plan} == {"Day04", "Day17"}


def test_mixed_month_and_fixed_naming(roots, make_config):
    source, _ = roots
    dated = [(f"sep02-{i}.jpg", datetime(2026, 9, 2)) for i in range(8)]
    dated += [(f"sep14-{i}.jpg", datetime(2026, 9, 14)) for i in range(14)]
    dated += [(f"sep27-{i}.jpg", datetime(2026, 9, 27)) for i in range(31)]
    _, plan = plan_for_dates(source, make_config, dated)
    assert sum(p.day_folder == "_sparse" for p in plan) == 22
    assert sum(p.day_folder == "Day27" for p in plan) == 31
    assert {p.month_folder for p in plan} == {"09-Sep"}


@pytest.mark.parametrize("value,folder", [
    (datetime(2026, 1, 31), "2026/01-Jan/Day31"),
    (datetime(2026, 2, 1), "2026/02-Feb/Day01"),
    (datetime(2026, 12, 31), "2026/12-Dec/Day31"),
    (datetime(2027, 1, 1), "2027/01-Jan/Day01"),
    (datetime(2026, 3, 9), "2026/03-Mar/Day09"),
    (datetime(2026, 3, 10), "2026/03-Mar/Day10"),
])
def test_calendar_boundaries_and_locale_independent_names(roots, make_config, value, folder):
    source, _ = roots
    name = value.strftime("file-%Y%m%d.jpg")
    _, plan = plan_for_dates(source, make_config, [(name, value)], threshold=1)
    assert plan[0].destination == f"{folder}/{name}"


def test_primary_types_count_and_cr2_sidecar_placement(roots, make_config):
    source, _ = roots
    dated = [(f"image-{i}.jpg", datetime(2026, 9, 27)) for i in range(13)]
    dated += [("raw.cr2", datetime(2026, 9, 27)), ("video.mp4", datetime(2026, 9, 27))]
    create_files(source, [name for name, _ in dated] + ["raw.xmp"])
    cfg = make_config(day_grouping={"threshold": 15})
    inventory = SourceScanner(cfg.section("media")).scan(source)
    timestamps = {name: ResolvedTimestamp(value) for name, value in dated}
    plan = ArchivePlanner(cfg.section("day_grouping")).build(inventory.eligible, timestamps)
    by_name = {p.media.path.name: p for p in plan}
    assert len(inventory.primary_media) == 15 and len(inventory.associated_sidecars) == 1
    assert all(p.day_classification == "DAY_FOLDER" for p in plan)
    assert by_name["raw.cr2"].destination == "2026/09-Sep/Day27/CR2/raw.cr2"
    assert by_name["raw.xmp"].destination == "2026/09-Sep/Day27/CR2/raw.xmp"


def test_sidecars_do_not_count_and_ambiguous_is_not_guessed(roots, make_config):
    source, _ = roots
    dated = [(f"image-{i}.jpg", datetime(2026, 9, 27)) for i in range(14)]
    create_files(source, [name for name, _ in dated] + ["image-0.aae", "pair.jpg", "pair.cr2", "pair.xmp", "alone.xmp"])
    cfg = make_config(day_grouping={"threshold": 15})
    inventory = SourceScanner(cfg.section("media")).scan(source)
    timestamps = {f.relative_path: ResolvedTimestamp(datetime(2026, 9, 27) if f.path.name.startswith("image-") else datetime(2026, 9, 26))
                  for f in inventory.primary_media}
    plan = ArchivePlanner(cfg.section("day_grouping")).build(inventory.eligible, timestamps)
    image_entries = [p for p in plan if p.media.path.name.startswith("image-")]
    assert all(p.day_classification == "SPARSE" for p in image_entries)
    assert next(p for p in plan if p.media.path.name == "image-0.aae").destination.endswith("/_sparse/image-0.aae")
    assert next(p for p in plan if p.media.path.name == "pair.cr2").destination == "2026/09-Sep/_sparse/CR2/pair.cr2"
    reasons = {f.path.name: f.reason for f in inventory.files}
    assert reasons["pair.xmp"] == reasons["alone.xmp"] == "UNASSOCIATED_SIDECAR"


def test_cr2_and_same_stem_jpg_count_as_two(roots, make_config):
    source, _ = roots
    inventory, plan = plan_for_dates(source, make_config,
                                     [("shot.cr2", datetime(2026, 9, 27)), ("shot.jpg", datetime(2026, 9, 27))], threshold=2)
    assert len(inventory.primary_media) == 2
    assert all(p.daily_primary_media_count == 2 and p.day_classification == "DAY_FOLDER" for p in plan)


def test_fourteen_jpg_and_one_mp4_reaches_threshold(roots, make_config):
    source, _ = roots
    dated = [(f"still-{i}.jpg", datetime(2026, 9, 27)) for i in range(14)]
    dated.append(("clip.mp4", datetime(2026, 9, 27)))
    _, plan = plan_for_dates(source, make_config, dated)
    assert len(plan) == 15
    assert all(p.daily_primary_media_count == 15 and p.day_classification == "DAY_FOLDER" for p in plan)


def test_collision_and_determinism(roots, make_config):
    source, _ = roots
    create_files(source, ["a/007.JPG", "b/007.JPG", "other.bmp"])
    cfg = make_config()
    files = SourceScanner(cfg.section("media")).scan(source).eligible
    dates = {f.relative_path: ResolvedTimestamp() for f in files}
    planner = ArchivePlanner(cfg.section("day_grouping"))
    plan = planner.build(files, dates)
    assert plan == planner.build(list(reversed(files)), dates)
    assert planner.validate(plan, files) == {"a/007.JPG", "b/007.JPG"}


def test_space_margin(roots, make_config, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("photo_archive_organizer.safety.shutil.disk_usage", lambda p: SimpleNamespace(free=330))
    plans = [SimpleNamespace(media=SimpleNamespace(size=100)) for _ in range(2)]
    result = SpaceEstimator().estimate(plans, roots[1], 1, 10)
    assert result["required_bytes"] == 330 and result["status"] == "PASS"
