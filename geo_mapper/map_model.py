import json
from dataclasses import replace
from pathlib import Path

from .clustering import cluster_events
from .config import MODEL_SCHEMA_VERSION, MONTH_NAMES
from .media_identity import MediaIdentityResolver
from .metadata import normalize_metadata
from .models import MapperWarning, MonthMapModel, MonthSummary, YearMapModel, jsonable
from .notes import read_notes
from .sequence import build_day_groups


def build_month_model(month, files, raw_metadata):
    normalized = {path: normalize_metadata(path, raw_metadata[path], month) for path in files}
    events, identity_warnings, logical_count = MediaIdentityResolver().resolve(month.path, files, normalized)
    warnings = [MapperWarning("METADATA", warning, path.relative_to(month.path).as_posix())
                for path, metadata in normalized.items() for warning in metadata.warnings]
    warnings.extend(MapperWarning("IDENTITY", message, path.relative_to(month.path).as_posix())
                    for path, message in identity_warnings)
    notes = read_notes(month.path)
    if notes:
        warnings.extend(MapperWarning("NOTES", warning, "map_notes.md") for warning in notes.warnings)
    return MonthMapModel(
        month.year, month.month, month.canonical_label, month.path.name, month.context, notes,
        len(files), logical_count,
        sum(m.latitude is not None and m.longitude is not None for m in normalized.values()),
        events, build_day_groups(events), cluster_events(events), warnings,
    )


def enrich_clusters(model, cache, geocoder=None):
    clusters, warnings = [], list(model.warnings)
    for cluster in model.clusters:
        provider = geocoder.provider if geocoder else "geonames"
        record = cache.get(provider, cluster.latitude, cluster.longitude)
        if record is None and geocoder is not None:
            try:
                place = geocoder.lookup(cluster.latitude, cluster.longitude)
                if place:
                    record = {"place_name": place.place_name, "admin1": place.admin1,
                              "country": place.country, "country_code": place.country_code,
                              "provider": provider, "schema_version": 1}
                    cache.put(provider, cluster.latitude, cluster.longitude, record)
            except Exception as exc:
                warnings.append(MapperWarning("GEOCODING", f"place lookup failed: {exc}", cluster.cluster_id))
        clusters.append(replace(cluster, place_name=record.get("place_name") if record else None,
                                admin1=record.get("admin1") if record else None,
                                country=record.get("country") if record else None))
    model.clusters = clusters
    model.warnings = warnings
    return model


def month_display_title(model):
    context = model.human_notes.title if model.human_notes and model.human_notes.title else model.folder_context
    title = f"{MONTH_NAMES[model.month]} {model.year}"
    return f"{title} - {context}" if context else title


def month_summary(model, output_name="travel_map.html"):
    derived = sorted({c.place_name for c in model.clusters if c.place_name}, key=str.casefold)
    return MonthSummary(model.year, model.month, month_display_title(model), model.source_folder_name,
                        f"{model.source_folder_name}/{output_name}", model.total_media_examined,
                        len(model.geo_events), len(model.day_groups), model.folder_context,
                        model.human_notes.plain_text_excerpt if model.human_notes else None,
                        model.human_notes.places if model.human_notes else (), tuple(derived))


def build_year_model(year_path: Path, models, output_name="travel_map.html"):
    notes = read_notes(year_path)
    warnings = [MapperWarning("NOTES", warning, "map_notes.md") for warning in notes.warnings] if notes else []
    ordered = sorted(models, key=lambda model: model.month)
    return YearMapModel(int(year_path.name), notes,
                        [month_summary(model, output_name) for model in ordered],
                        [event for model in ordered for event in model.geo_events], warnings)


def write_model(path: Path, model):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": MODEL_SCHEMA_VERSION, "model": jsonable(model)}
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
