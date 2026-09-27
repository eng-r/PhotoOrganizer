import os
from dataclasses import dataclass, field

from .cache import EnrichmentCache
from .discovery import discover_media
from .geocoding import GeoNamesGeocoder
from .html_renderer import render_month, render_year
from .map_model import build_month_model, build_year_model, enrich_clusters, write_model
from .models import MapperWarning, TargetScope
from .reporting import month_report, year_report


@dataclass
class MonthProcessingResult:
    month: object
    success: bool
    model: object | None = None
    error: str = ""


@dataclass
class BatchResult:
    years_discovered: int = 0
    years_processed: int = 0
    months_discovered: int = 0
    months_succeeded: int = 0
    months_failed: int = 0
    monthly_maps_created: int = 0
    annual_maps_created: int = 0
    annual_maps_skipped: int = 0
    months_with_no_gps: int = 0
    warnings: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_annual: list[str] = field(default_factory=list)

    @property
    def exit_code(self):
        return 1 if self.errors else 0


def write_html(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def process_month(month, args, adapter, geocoder):
    try:
        files = discover_media(month)
        raw = adapter.extract(files)
        model = build_month_model(month, files, raw)
        cache = EnrichmentCache(month.path / ".geo_mapper/cache.json").load()
        model = enrich_clusters(model, cache, geocoder)
        model.warnings.extend(MapperWarning("CACHE", warning, ".geo_mapper/cache.json") for warning in cache.warnings)
        write_model(month.path / ".geo_mapper/geo_data.json", model)
        cache.save()
        output = month.path / args.output_name
        write_html(output, render_month(model))
        month_report(model, output)
        return MonthProcessingResult(month, True, model)
    except Exception as exc:
        return MonthProcessingResult(month, False, error=str(exc))


def process_target(resolved, years, args, adapter, logger):
    result = BatchResult(years_discovered=len(years), months_discovered=sum(len(months) for months in years.values()))
    username = os.environ.get("GEO_MAPPER_GEONAMES_USERNAME")
    geocoder = None if args.offline or args.no_geocode or not username else GeoNamesGeocoder(username)
    for year in sorted(years):
        months = years[year]
        models = []
        failed = []
        for month in months:
            outcome = process_month(month, args, adapter, geocoder)
            if outcome.success:
                model = outcome.model
                models.append(model)
                result.months_succeeded += 1
                result.monthly_maps_created += 1
                result.months_with_no_gps += not model.geo_events
                result.warnings += len(model.warnings)
                for warning in model.warnings:
                    logger.debug("%s %s: %s", warning.category, warning.path, warning.message)
            else:
                failed.append(outcome)
                result.months_failed += 1
                message = f"{month.path}: {outcome.error}"
                result.errors.append(message)
                print(f"ERROR: month failed: {message}")
        result.years_processed += 1
        if resolved.scope == TargetScope.MONTH:
            continue
        year_path = resolved.path if resolved.scope == TargetScope.YEAR else resolved.path / str(year)
        if failed:
            result.annual_maps_skipped += 1
            reason = f"{year}: incomplete year processing ({len(failed)} of {len(months)} months failed)"
            result.skipped_annual.append(reason)
            print(f"Annual map not regenerated: {reason}")
            continue
        if not models:
            result.annual_maps_skipped += 1
            reason = f"{year}: no non-empty eligible months"
            result.skipped_annual.append(reason)
            print(f"Annual map not generated: {reason}")
            continue
        try:
            year_model = build_year_model(year_path, models, args.output_name)
            output = year_path / f"travel_map_{year}.html"
            year_data = year_path / ".geo_mapper/year_data.json"
            rendered = render_year(year_model)
            write_model(year_data, year_model)
            write_html(output, rendered)
            year_report(year_model, output)
            result.annual_maps_created += 1
        except Exception as exc:
            result.annual_maps_skipped += 1
            reason = f"{year}: annual generation failed: {exc}"
            result.skipped_annual.append(reason)
            result.errors.append(reason)
            print(f"ERROR: {reason}")
    return result
