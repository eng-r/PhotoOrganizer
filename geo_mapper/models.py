from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from enum import Enum


class TargetScope(str, Enum):
    MONTH = "month"
    YEAR = "year"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class ResolvedTarget:
    path: Path
    scope: TargetScope
    year: int | None = None
    month: int | None = None
    month_folder_context: str | None = None


@dataclass(frozen=True)
class MonthFolder:
    path: Path
    year: int
    month: int
    canonical_label: str
    context: str | None = None


@dataclass(frozen=True)
class HumanNotes:
    title: str | None
    places: tuple[str, ...]
    markdown_text: str
    safe_html: str
    plain_text_excerpt: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedMetadata:
    source_path: Path
    resolved_date: date | None
    capture_datetime: datetime | None
    capture_datetime_source: str | None
    capture_timezone_offset: str | None
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    make: str | None
    model: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeoPhotoEvent:
    event_id: str
    representative_path: Path
    related_paths: tuple[Path, ...]
    filename: str
    resolved_date: date
    capture_datetime: datetime | None
    capture_datetime_source: str | None
    latitude: float
    longitude: float
    altitude_m: float | None
    make: str | None
    model: str | None
    place_id: str | None = None


@dataclass(frozen=True)
class SequenceSegment:
    date: date
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class DayGroup:
    date: date
    event_count: int
    bounds: tuple[float, float, float, float]
    altitude_min_m: float | None
    altitude_max_m: float | None
    sequences: tuple[SequenceSegment, ...]


@dataclass(frozen=True)
class GeoCluster:
    cluster_id: str
    latitude: float
    longitude: float
    event_ids: tuple[str, ...]
    place_name: str | None = None
    admin1: str | None = None
    country: str | None = None


@dataclass(frozen=True)
class MapperWarning:
    category: str
    message: str
    path: str = ""


@dataclass
class MonthMapModel:
    year: int
    month: int
    canonical_month_label: str
    source_folder_name: str
    folder_context: str | None
    human_notes: HumanNotes | None
    total_media_examined: int
    logical_event_count: int
    geotagged_physical_files: int
    geo_events: list[GeoPhotoEvent]
    day_groups: list[DayGroup]
    clusters: list[GeoCluster]
    warnings: list[MapperWarning] = field(default_factory=list)


@dataclass(frozen=True)
class MonthSummary:
    year: int
    month: int
    display_title: str
    source_folder_name: str
    relative_html_path: str
    total_media_examined: int
    geo_event_count: int
    gps_day_count: int
    folder_context: str | None
    notes_excerpt: str | None
    human_place_labels: tuple[str, ...]
    derived_place_labels: tuple[str, ...]


@dataclass
class YearMapModel:
    year: int
    human_notes: HumanNotes | None
    months: list[MonthSummary]
    geo_events: list[GeoPhotoEvent]
    warnings: list[MapperWarning] = field(default_factory=list)


def jsonable(value: Any):
    if hasattr(value, "__dataclass_fields__"):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (Path, date, datetime)):
        return value.isoformat() if isinstance(value, (date, datetime)) else value.as_posix()
    return value
