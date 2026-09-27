import json
import os
import shutil
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import pytest

from geo_mapper.cache import EnrichmentCache
from geo_mapper.cli import parser, run
from geo_mapper.clustering import cluster_events, haversine_km
from geo_mapper.discovery import (DiscoveryError, discover_media, discover_target, parse_month_folder,
                                  resolve_scope, resolve_target)
from geo_mapper.exiftool_adapter import ExifToolAdapter, ExifToolError
from geo_mapper.geocoding import PlaceInfo
from geo_mapper.html_renderer import render_month, render_year
from geo_mapper.map_model import build_month_model, build_year_model, enrich_clusters, write_model
from geo_mapper.media_identity import MediaIdentityResolver
from geo_mapper.metadata import normalize_metadata, validate_gps
from geo_mapper.models import GeoPhotoEvent, MonthFolder, TargetScope
from geo_mapper.notes import read_notes, render_safe_markdown
from geo_mapper.sequence import build_day_groups


def media(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def month(tmp_path, name="03-Mar.Ecuador", year=2026):
    path = tmp_path / str(year) / name
    path.mkdir(parents=True)
    return parse_month_folder(path)


def record(path, date="2026:03:04 05:06:07", lat=29.76, lon=-95.37, altitude=12):
    value = {"SourceFile": str(path), "DateTimeOriginal": date, "GPSLatitude": lat,
             "GPSLongitude": lon, "GPSAltitude": altitude, "Make": "Camera", "Model": "One"}
    return value


@pytest.mark.parametrize("name,context", [
    ("03-Mar", None), ("03-Mar.Ecuador", "Ecuador"), ("03-Mar_Africa", "Africa"),
    ("03-Mar Ecuador", "Ecuador"), ("03-Mar [Ecuador]", "Ecuador"),
])
def test_month_folder_variants(tmp_path, name, context):
    path = tmp_path / "2026" / name
    path.mkdir(parents=True)
    parsed = parse_month_folder(path)
    assert (parsed.month, parsed.canonical_label, parsed.context) == (3, "03-Mar", context)


@pytest.mark.parametrize("name", ["03-May", "3-Mar", "03-Mar.", "March"])
def test_invalid_month_folders(tmp_path, name):
    path = tmp_path / "2026" / name
    path.mkdir(parents=True)
    with pytest.raises(DiscoveryError):
        parse_month_folder(path)


def test_scope_and_sparse_only_discovery(tmp_path):
    m = month(tmp_path)
    media(m.path / "_sparse/A.JPG")
    media(m.path / "_sparse/A.XMP")
    (tmp_path / "2026/unrelated").mkdir()
    scope, years = resolve_scope(tmp_path)
    assert scope == TargetScope.ARCHIVE and [x.month for x in years[2026]] == [3]
    assert [p.name for p in discover_media(m)] == ["A.JPG"]
    assert resolve_scope(m.path)[0] == TargetScope.MONTH
    assert resolve_scope(m.path.parent)[0] == TargetScope.YEAR


def test_empty_month_omitted(tmp_path):
    empty = month(tmp_path)
    (empty.path / "map_notes.md").write_text("notes only")
    filled = tmp_path / "2026/04-Apr"
    media(filled / "Day01/a.jpg")
    assert [m.month for m in resolve_scope(tmp_path / "2026")[1][2026]] == [4]


def test_notes_plain_front_matter_and_safety(tmp_path):
    m = month(tmp_path)
    original = "---\ntitle: Ecuador\nplaces:\n  - Quito\n  - Banos\n---\nHello **world**.\n\n<script>alert(1)</script> [bad](javascript:alert(1)) [good](https://example.com)"
    path = m.path / "map_notes.md"
    path.write_text(original, encoding="utf-8")
    notes = read_notes(m.path)
    assert notes.title == "Ecuador" and notes.places == ("Quito", "Banos")
    assert "<script>" not in notes.safe_html and "javascript:" not in notes.safe_html
    assert 'href="https://example.com"' in notes.safe_html
    assert read_notes(m.path).plain_text_excerpt == notes.plain_text_excerpt
    assert path.read_text(encoding="utf-8") == original


def test_malformed_notes_warns(tmp_path):
    m = month(tmp_path)
    (m.path / "map_notes.md").write_text("---\ntitle: Missing end")
    assert read_notes(m.path).warnings
    assert "&lt;b&gt;" in render_safe_markdown("<b>unsafe</b>")


@pytest.mark.parametrize("lat,lon,valid", [(0, 0, True), (0, -20, True), (-12, 0, True), (91, 0, False), (0, 181, False), (1, None, False)])
def test_gps_validation(lat, lon, valid):
    latitude, longitude, warning = validate_gps(lat, lon)
    assert (latitude is not None and longitude is not None) is valid
    assert bool(warning) is not valid


def test_metadata_dates_offsets_altitudes_and_day_fallback(tmp_path):
    m = month(tmp_path)
    path = media(m.path / "Day04/a.jpg")
    normalized = normalize_metadata(path, {"DateTimeOriginal": "2026:03:04 05:06:07", "SubSecTimeOriginal": "25",
                                           "OffsetTimeOriginal": "-06:00", "GPSLatitude": -1, "GPSLongitude": 2,
                                           "GPSAltitude": -5}, m)
    assert normalized.capture_datetime.isoformat() == "2026-03-04T05:06:07.250000-06:00"
    assert normalized.altitude_m == -5 and normalized.resolved_date.isoformat() == "2026-03-04"
    fallback = normalize_metadata(path, {}, m)
    assert fallback.capture_datetime_source == "ArchiveDayFolder" and fallback.resolved_date.day == 4
    assert fallback.capture_datetime is None


def test_date_only_filename_does_not_invent_sequence_time(tmp_path):
    m = month(tmp_path)
    path = media(m.path / "_sparse/IMG-20260304-WA0001.jpg")
    normalized = normalize_metadata(path, {"GPSLatitude": 1, "GPSLongitude": 2}, m)
    assert normalized.resolved_date.isoformat() == "2026-03-04"
    assert normalized.capture_datetime is None


def test_partial_and_malformed_metadata_warns(tmp_path):
    m = month(tmp_path)
    path = media(m.path / "_sparse/a.jpg")
    normalized = normalize_metadata(path, {"GPSLatitude": 1, "GPSAltitude": "bad", "DateTimeOriginal": "bad"}, m)
    assert normalized.latitude is None and len(normalized.warnings) >= 3


def test_jpg_raw_pair_is_one_event_and_jpg_wins(tmp_path):
    m = month(tmp_path)
    jpg, raw = media(m.path / "Day04/IMG_1.JPG"), media(m.path / "Day04/IMG_1.CR2")
    metadata = {p: normalize_metadata(p, record(p), m) for p in (jpg, raw)}
    events, warnings, logical = MediaIdentityResolver().resolve(m.path, [raw, jpg], metadata)
    assert logical == 1 and len(events) == 1 and events[0].representative_path == jpg
    assert events[0].event_id == MediaIdentityResolver().resolve(m.path, [jpg, raw], metadata)[0][0].event_id
    assert not warnings


def test_organizer_cr2_leaf_pairs_with_parent_jpg(tmp_path):
    m = month(tmp_path)
    jpg, raw = media(m.path / "Day04/IMG_2.JPG"), media(m.path / "Day04/CR2/IMG_2.CR2")
    metadata = {p: normalize_metadata(p, record(p), m) for p in (jpg, raw)}
    events, _, logical = MediaIdentityResolver().resolve(m.path, [jpg, raw], metadata)
    assert logical == len(events) == 1 and events[0].representative_path == jpg


def test_same_stem_different_day_folders_not_collapsed(tmp_path):
    m = month(tmp_path)
    a, b = media(m.path / "Day04/IMG.JPG"), media(m.path / "Day05/IMG.JPG")
    metadata = {a: normalize_metadata(a, record(a, "2026:03:04 01:00:00"), m),
                b: normalize_metadata(b, record(b, "2026:03:05 01:00:00"), m)}
    events, _, logical = MediaIdentityResolver().resolve(m.path, [a, b], metadata)
    assert logical == len(events) == 2


def event(name, when, lat, lon, altitude=None):
    path = Path(name)
    return GeoPhotoEvent("id-" + name, path, (path,), name, when.date(), when, "DateTimeOriginal", lat, lon, altitude, None, None)


def test_distance_clustering_and_sequence_gaps():
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.195, rel=.001)
    events = [event("a", datetime(2026, 3, 4, 8), 29.7600, -95.3700, 0),
              event("b", datetime(2026, 3, 4, 9), 29.7601, -95.3701, 10),
              event("c", datetime(2026, 3, 4, 15), 40.0, -120.0, -2)]
    assert len(cluster_events(events)) == 2
    groups = build_day_groups(events)
    assert groups[0].altitude_min_m == -2 and groups[0].altitude_max_m == 10
    assert [s.event_ids for s in groups[0].sequences] == [("id-a", "id-b")]


def test_missing_times_do_not_make_sequence():
    first = event("a", datetime(2026, 3, 4, 8), 1, 1)
    second = GeoPhotoEvent("id-b", Path("b"), (Path("b"),), "b", first.resolved_date, None, None, 1.1, 1.1, None, None, None)
    assert not build_day_groups([first, second])[0].sequences


def test_cache_hit_corruption_and_deterministic_save(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json")
    cache = EnrichmentCache(path).load()
    assert cache.warnings
    cache.put("geonames", 1.23456, 2.34567, {"place_name": "Here"})
    cache.save()
    assert EnrichmentCache(path).load().get("geonames", 1.23456, 2.34567)["place_name"] == "Here"
    assert json.loads(path.read_text())["schema_version"] == 1


def test_cached_and_mocked_geocoding(tmp_path):
    m = month(tmp_path)
    path = media(m.path / "Day04/a.jpg")
    model = build_month_model(m, [path], {path: record(path)})
    cache = EnrichmentCache(tmp_path / "cache.json")
    class FakeGeocoder:
        provider = "geonames"
        def lookup(self, latitude, longitude):
            return PlaceInfo("Houston", "Texas", "United States", "US")
    enrich_clusters(model, cache, FakeGeocoder())
    assert model.clusters[0].place_name == "Houston"
    enrich_clusters(model, cache, None)
    assert model.clusters[0].place_name == "Houston"


def test_models_render_escape_and_round_trip(tmp_path):
    m = month(tmp_path)
    path = media(m.path / "Day04/bad & name.jpg")
    model = build_month_model(m, [path], {path: record(path)})
    html = render_month(model)
    assert "Memory map" in html and "Photo sequence" in html and "bad &amp; name.jpg" in html
    assert 'fetch("geo_data.json")' not in html
    output = tmp_path / "geo.json"
    write_model(output, model)
    assert json.loads(output.read_text())["schema_version"] == 1


def test_zero_gps_month_and_zero_gps_year_render(tmp_path):
    m = month(tmp_path)
    path = media(m.path / "Day04/a.jpg")
    model = build_month_model(m, [path], {path: {}})
    assert "No GPS-tagged photographs" in render_month(model)
    year = build_year_model(m.path.parent, [model])
    annual = render_year(year)
    assert "No GPS-tagged photographs" in annual and "03-Mar.Ecuador/travel_map.html" in annual


class FakeAdapter:
    def __init__(self, rows):
        self.rows, self.checked, self.calls = rows, False, []
    def check(self):
        self.checked = True
        return "fake"
    def extract(self, paths):
        self.calls.append(tuple(paths))
        return {path: self.rows.get(path.name, record(path)) for path in paths}


def args(path, **values):
    defaults = dict(target_path=path, scope=None, rebuild=False, offline=True, no_geocode=False, verbose=False,
                    dry_run=False, output_name="travel_map.html")
    defaults.update(values)
    return Namespace(**defaults)


def test_month_cli_does_not_touch_annual_page(tmp_path):
    m = month(tmp_path)
    media(m.path / "Day04/a.jpg")
    annual = m.path.parent / "travel_map_2026.html"
    annual.write_text("keep")
    notes = m.path / "map_notes.md"
    notes.write_text("keep notes")
    assert run(args(m.path), FakeAdapter({})) == 0
    assert (m.path / "travel_map.html").is_file() and annual.read_text() == "keep"
    assert notes.read_text() == "keep notes"


def test_year_and_archive_cli_outputs(tmp_path):
    march = month(tmp_path, "03-Mar")
    april = tmp_path / "2026/04-Apr"
    media(march.path / "Day04/a.jpg")
    media(april / "_sparse/b.jpeg")
    assert run(args(tmp_path / "2026"), FakeAdapter({})) == 0
    assert (tmp_path / "2026/travel_map_2026.html").is_file()
    assert (april / "travel_map.html").is_file()
    other = month(tmp_path, "01-Jan", 2027)
    media(other.path / "Day01/c.jpg")
    assert run(args(tmp_path), FakeAdapter({})) == 0
    assert (tmp_path / "2027/travel_map_2027.html").is_file()


def test_dry_run_writes_nothing_and_skips_adapter(tmp_path):
    m = month(tmp_path)
    media(m.path / "Day04/a.jpg")
    adapter = FakeAdapter({})
    assert run(args(m.path, dry_run=True), adapter) == 0
    assert not adapter.checked and not (m.path / "travel_map.html").exists() and not (m.path / ".geo_mapper").exists()


def test_explicit_scope_validates_instead_of_forcing(tmp_path):
    m = month(tmp_path)
    assert resolve_target(m.path, "month").scope == TargetScope.MONTH
    assert resolve_target(m.path.parent, "year").scope == TargetScope.YEAR
    assert resolve_target(tmp_path, "archive").scope == TargetScope.ARCHIVE
    with pytest.raises(DiscoveryError, match="does not satisfy MONTH"):
        resolve_target(m.path.parent, "month")


def test_noncanonical_year_and_ambiguous_target_rejected(tmp_path):
    bad = tmp_path / "2025_backup"
    bad.mkdir()
    with pytest.raises(DiscoveryError, match="Unable to determine"):
        resolve_target(bad)
    vacation = tmp_path / "Vacation"
    vacation.mkdir()
    (vacation / "nested/2026").mkdir(parents=True)
    with pytest.raises(DiscoveryError, match="Unable to determine"):
        resolve_target(vacation)


def test_archive_years_and_months_sort_numerically(tmp_path):
    for year, month_name in [(2026, "12-Dec"), (2024, "10-Oct"), (2025, "03-Mar.Z")]:
        media(tmp_path / str(year) / month_name / "_sparse/a.jpg")
    resolved = resolve_target(tmp_path)
    years = discover_target(resolved)
    assert list(years) == [2024, 2025, 2026]
    assert [m.month for m in years[2025]] == [3]


def test_generated_artifacts_never_become_media(tmp_path):
    m = month(tmp_path)
    media(m.path / "_sparse/photo.jpg")
    media(m.path / ".geo_mapper/thumbnails/generated.jpg")
    (m.path / "travel_map.html").write_text("generated")
    (m.path / "travel_map_2026.html").write_text("generated")
    (m.path / "map_notes.md").write_text("notes")
    (m.path / ".geo_mapper/cache.json").write_text("{}")
    assert [p.name for p in discover_media(m)] == ["photo.jpg"]


def test_no_argument_parser_uses_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parsed = parser().parse_args([])
    assert parsed.target_path == tmp_path


def test_fatal_month_preserves_annual_and_continues_years(tmp_path):
    jan_2025 = tmp_path / "2025/01-Jan"
    feb_2025 = tmp_path / "2025/02-Feb"
    jan_2026 = tmp_path / "2026/01-Jan"
    media(jan_2025 / "Day01/fail.jpg")
    media(feb_2025 / "Day01/good.jpg")
    media(jan_2026 / "Day01/later.jpg")
    annual_2025 = tmp_path / "2025/travel_map_2025.html"
    annual_2025.write_text("known-good-annual")
    class FailingMonthAdapter(FakeAdapter):
        def extract(self, paths):
            if any("01-Jan" in path.parts and "2025" in path.parts for path in paths):
                raise RuntimeError("injected fatal month failure")
            return super().extract(paths)
    assert run(args(tmp_path), FailingMonthAdapter({})) == 1
    assert annual_2025.read_text() == "known-good-annual"
    assert (feb_2025 / "travel_map.html").is_file()
    assert (tmp_path / "2026/travel_map_2026.html").is_file()
    assert not (tmp_path / "Life_Map.html").exists()


def test_direct_year_and_archive_year_data_are_equivalent(tmp_path):
    m = month(tmp_path, "03-Mar")
    media(m.path / "Day04/a.jpg")
    adapter = FakeAdapter({})
    assert run(args(tmp_path / "2026"), adapter) == 0
    direct = (tmp_path / "2026/.geo_mapper/year_data.json").read_text()
    assert run(args(tmp_path), FakeAdapter({})) == 0
    assert (tmp_path / "2026/.geo_mapper/year_data.json").read_text() == direct


def test_demo_batch_files_cover_scopes_and_current_directory():
    root = Path(__file__).parents[1]
    assert '"%CD%"' in (root / "geo_mapper.bat").read_text()
    assert "--scope archive" in (root / "demo_archive.bat").read_text()
    assert "--scope year" in (root / "demo_year.bat").read_text()
    assert "--scope month" in (root / "demo_month.bat").read_text()
    dry = (root / "demo_offline_dry_run.bat").read_text()
    assert "--offline --dry-run" in dry and "TARGET=%CD%" in dry


def test_exiftool_adapter_batches_with_argument_file(tmp_path, monkeypatch):
    paths = [media(tmp_path / "one image.jpg"), media(tmp_path / "-two.jpg")]
    calls = []
    class Result:
        returncode = 0
        stderr = ""
        stdout = ""
    def fake_run(command, **kwargs):
        calls.append((command, kwargs.get("input")))
        result = Result()
        if "-ver" in command:
            result.stdout = "13.59\n"
        else:
            result.stdout = json.dumps([{"SourceFile": str(path.resolve()), "GPSLatitude": 1, "GPSLongitude": 2} for path in paths])
        return result
    monkeypatch.setattr("geo_mapper.exiftool_adapter.shutil.which", lambda _: "exiftool")
    monkeypatch.setattr("geo_mapper.exiftool_adapter.subprocess.run", fake_run)
    adapter = ExifToolAdapter(batch_size=10)
    assert adapter.check() == "13.59"
    rows = adapter.extract(paths)
    command, input_text = calls[1]
    assert len(rows) == 2 and "-n" in command and command[-2:] == ["-@", "-"]
    assert str(paths[0].resolve()) in input_text and str(paths[0].resolve()) not in command


def test_exiftool_missing_is_actionable(monkeypatch):
    monkeypatch.setattr("geo_mapper.exiftool_adapter.shutil.which", lambda _: None)
    with pytest.raises(ExifToolError, match="GEO_MAPPER_EXIFTOOL"):
        ExifToolAdapter().check()


def real_exif_command():
    override = os.environ.get("EXIFTOOL_TEST_COMMAND")
    if override:
        return json.loads(override)
    if shutil.which("exiftool"):
        return ["exiftool"]
    local = Path(__file__).parents[2] / ".tools/exiftool-13.59/exiftool"
    if local.is_file() and shutil.which("perl"):
        return ["perl", str(local)]
    pytest.skip("real ExifTool not available")


@pytest.mark.exiftool
def test_real_exiftool_adapter_reads_tiny_jpeg(tmp_path):
    from PIL import Image
    path = tmp_path / "tiny image.jpg"
    exif = Image.Exif()
    exif[36867] = "2026:03:04 05:06:07"
    Image.new("RGB", (3, 3)).save(path, exif=exif)
    adapter = ExifToolAdapter(command=real_exif_command())
    adapter.check()
    row = adapter.extract([path])[path]
    assert any(key.endswith(":DateTimeOriginal") or key == "DateTimeOriginal" for key in row)
