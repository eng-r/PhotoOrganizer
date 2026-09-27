import argparse
import logging
import os
import sys
from pathlib import Path

from .cache import EnrichmentCache
from .discovery import DiscoveryError, discover_media, resolve_scope
from .exiftool_adapter import ExifToolAdapter, ExifToolError
from .geocoding import GeoNamesGeocoder
from .html_renderer import render_month, render_year
from .logging_utils import configure_logging
from .map_model import build_month_model, build_year_model, enrich_clusters, write_model
from .models import MapperWarning
from .reporting import month_report, year_report


LOGGER = logging.getLogger(__name__)


def parser():
    result = argparse.ArgumentParser(description="Generate read-only monthly and annual maps from an organized photo archive.")
    result.add_argument("target_path", type=Path)
    result.add_argument("--rebuild", action="store_true", help="Regenerate outputs (the default; retained for explicit scripts).")
    result.add_argument("--offline", action="store_true", help="Prohibit network enrichment while still using cached place names.")
    result.add_argument("--no-geocode", action="store_true", help="Disable live reverse geocoding.")
    result.add_argument("--verbose", action="store_true")
    result.add_argument("--dry-run", action="store_true", help="Discover and validate without extracting metadata or writing files.")
    result.add_argument("--output-name", default="travel_map.html")
    return result


def _write_html(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def run(args, adapter=None):
    configure_logging(args.verbose)
    scope, years = resolve_scope(args.target_path)
    LOGGER.debug("Resolved %s target with years: %s", scope, sorted(years))
    discovered = sum(len(months) for months in years.values())
    if args.dry_run:
        for year, months in years.items():
            for month in months:
                print(f"Would process {month.path} ({len(discover_media(month))} media files)")
            if scope != "month":
                print(f"Would generate {args.target_path if scope == 'year' else args.target_path / str(year)}/travel_map_{year}.html")
        print(f"Dry run complete: {discovered} month(s); no files written; no network calls made.")
        return 0
    adapter = adapter or ExifToolAdapter()
    adapter.check()
    username = os.environ.get("GEO_MAPPER_GEONAMES_USERNAME")
    geocoder = None if args.offline or args.no_geocode or not username else GeoNamesGeocoder(username)
    processed, no_gps, warning_count = 0, 0, 0
    for year, months in years.items():
        models = []
        for month in months:
            files = discover_media(month)
            raw = adapter.extract(files)
            model = build_month_model(month, files, raw)
            cache = EnrichmentCache(month.path / ".geo_mapper/cache.json").load()
            model = enrich_clusters(model, cache, geocoder)
            model.warnings.extend(MapperWarning("CACHE", warning, ".geo_mapper/cache.json") for warning in cache.warnings)
            for warning in model.warnings:
                LOGGER.debug("%s %s: %s", warning.category, warning.path, warning.message)
            write_model(month.path / ".geo_mapper/geo_data.json", model)
            cache.save()
            output = month.path / args.output_name
            _write_html(output, render_month(model))
            month_report(model, output)
            models.append(model)
            processed += 1
            no_gps += not model.geo_events
            warning_count += len(model.warnings)
        if scope != "month" and models:
            year_path = args.target_path if scope == "year" else args.target_path / str(year)
            year_model = build_year_model(year_path, models, args.output_name)
            write_model(year_path / ".geo_mapper/year_data.json", year_model)
            output = year_path / f"travel_map_{year}.html"
            _write_html(output, render_year(year_model))
            year_report(year_model, output)
    print("Geo Mapper complete")
    print(f"  months discovered: {discovered}")
    print(f"  months processed:  {processed}")
    print(f"  months with no GPS:{no_gps:3d}")
    print(f"  warnings:          {warning_count:3d}")
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if Path(args.output_name).name != args.output_name or not args.output_name.lower().endswith(".html"):
            raise DiscoveryError("--output-name must be a simple .html filename")
        return run(args)
    except (DiscoveryError, ExifToolError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("No source media files were modified.", file=sys.stderr)
        return 2
