import argparse
import logging
import sys
from pathlib import Path

from .config import MONTH_NAMES
from .discovery import DiscoveryError, discover_media, discover_target, resolve_target
from .exiftool_adapter import ExifToolAdapter, ExifToolError
from .logging_utils import configure_logging
from .models import TargetScope
from .orchestrator import process_target


LOGGER = logging.getLogger(__name__)


def parser():
    result = argparse.ArgumentParser(description="Generate read-only monthly and annual maps from an organized photo archive.")
    result.add_argument("target_path", nargs="?", type=Path, default=Path.cwd())
    result.add_argument("--scope", choices=[scope.value for scope in TargetScope], help="Validate an explicit target scope.")
    result.add_argument("--rebuild", action="store_true", help="Regenerate outputs (the default; retained for explicit scripts).")
    result.add_argument("--offline", action="store_true", help="Prohibit network enrichment while still using cached place names.")
    result.add_argument("--no-geocode", action="store_true", help="Disable live reverse geocoding.")
    result.add_argument("--verbose", action="store_true")
    result.add_argument("--dry-run", action="store_true", help="Discover and validate without extracting metadata or writing files.")
    result.add_argument("--output-name", default="travel_map.html")
    return result


def _startup_report(resolved, years):
    print("Geo Mapper")
    print(f"Target: {resolved.path}")
    print(f"Detected scope: {resolved.scope.value.upper()}")
    if resolved.scope == TargetScope.MONTH:
        print(f"Year: {resolved.year}")
        print(f"Month: {MONTH_NAMES[resolved.month]}")
        if resolved.month_folder_context:
            print(f"Context: {resolved.month_folder_context}")
    elif resolved.scope == TargetScope.YEAR:
        print(f"Year: {resolved.year}")
        print(f"Months discovered: {len(years[resolved.year])}")
    else:
        print("Years discovered: " + ", ".join(str(year) for year in sorted(years)))
        print(f"Months discovered: {sum(len(months) for months in years.values())}")


def run(args, adapter=None):
    configure_logging(args.verbose)
    resolved = resolve_target(args.target_path, args.scope)
    years = discover_target(resolved)
    LOGGER.debug("Resolved %s target with years: %s", resolved.scope.value, sorted(years))
    _startup_report(resolved, years)
    discovered = sum(len(months) for months in years.values())
    if args.dry_run:
        for year, months in years.items():
            for month in months:
                print(f"Would process {month.path} ({len(discover_media(month))} media files)")
            if resolved.scope != TargetScope.MONTH and months:
                year_path = resolved.path if resolved.scope == TargetScope.YEAR else resolved.path / str(year)
                print(f"Would generate {year_path / f'travel_map_{year}.html'}")
        print(f"Dry run complete: {discovered} month(s); no files written; no network calls made.")
        return 0
    adapter = adapter or ExifToolAdapter()
    adapter.check()
    result = process_target(resolved, years, args, adapter, LOGGER)
    print("Geo Mapper complete\n")
    print(f"  years discovered:      {result.years_discovered}")
    print(f"  years processed:       {result.years_processed}")
    print(f"  months discovered:     {result.months_discovered}")
    print(f"  months succeeded:      {result.months_succeeded}")
    print(f"  months failed:         {result.months_failed}")
    print(f"  monthly maps created:  {result.monthly_maps_created}")
    print(f"  annual maps created:   {result.annual_maps_created}")
    print(f"  annual maps skipped:   {result.annual_maps_skipped}")
    print(f"  warnings:              {result.warnings}")
    print(f"  errors:                {len(result.errors)}")
    for reason in result.skipped_annual:
        print(f"  skipped: {reason}")
    return result.exit_code


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
