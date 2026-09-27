import re
from datetime import datetime
from pathlib import Path

from photo_archive_organizer.timestamp_resolver import filename_date, parse_embedded

from .models import MonthFolder, NormalizedMetadata


def _tag(record, name):
    for key, value in record.items():
        if key.split(":")[-1] == name and value not in (None, ""):
            return value
    return None


def validate_gps(latitude, longitude):
    if latitude is None and longitude is None:
        return None, None, None
    if latitude is None or longitude is None:
        return None, None, "partial GPS coordinates"
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None, None, "malformed GPS coordinates"
    if not -90 <= lat <= 90:
        return None, None, f"latitude outside valid range: {lat}"
    if not -180 <= lon <= 180:
        return None, None, f"longitude outside valid range: {lon}"
    return lat, lon, None


def _date_from_archive_path(path: Path, month: MonthFolder):
    try:
        relative = path.relative_to(month.path)
    except ValueError:
        return None
    for part in relative.parts[:-1]:
        match = re.fullmatch(r"Day(0[1-9]|[12]\d|3[01])", part)
        if match:
            try:
                return datetime(month.year, month.month, int(match.group(1)))
            except ValueError:
                return None
    return None


def normalize_metadata(path: Path, record: dict, month: MonthFolder) -> NormalizedMetadata:
    warnings = []
    resolved_datetime, capture, source = None, None, None
    original = _tag(record, "DateTimeOriginal")
    create = _tag(record, "CreateDate")
    subsecond = _tag(record, "SubSecTimeOriginal")
    offset = _tag(record, "OffsetTimeOriginal")
    candidates = [("DateTimeOriginal", original), ("CreateDate", create)]
    for candidate_source, raw in candidates:
        if raw is None:
            continue
        value = str(raw)
        if candidate_source == "DateTimeOriginal" and subsecond and re.fullmatch(r"\d+", str(subsecond)) and len(value) == 19:
            value += "." + str(subsecond)
        if candidate_source == "DateTimeOriginal" and offset and re.fullmatch(r"[+-]\d{2}:\d{2}", str(offset)):
            value += str(offset)
        try:
            resolved_datetime, precision = parse_embedded(value)
            capture = resolved_datetime if precision != "day" else None
            source = candidate_source
            break
        except ValueError as exc:
            warnings.append(f"invalid {candidate_source}: {exc}")
    if resolved_datetime is None:
        try:
            resolved_datetime, precision = filename_date(path.name)
            capture = resolved_datetime if resolved_datetime and precision != "day" else None
            source = "FilenameDate" if resolved_datetime else None
        except ValueError as exc:
            warnings.append(f"invalid filename date: {exc}")
    if resolved_datetime is None:
        resolved_datetime = _date_from_archive_path(path, month)
        source = "ArchiveDayFolder" if resolved_datetime else None
    lat, lon, gps_warning = validate_gps(_tag(record, "GPSLatitude"), _tag(record, "GPSLongitude"))
    if gps_warning:
        warnings.append(gps_warning)
    altitude = _tag(record, "GPSAltitude")
    try:
        altitude = float(altitude) if altitude is not None else None
    except (TypeError, ValueError):
        warnings.append("malformed GPS altitude")
        altitude = None
    if _tag(record, "Error"):
        warnings.append(str(_tag(record, "Error")))
    return NormalizedMetadata(path, resolved_datetime.date() if resolved_datetime else None, capture, source,
                              str(offset) if offset else None, lat, lon, altitude,
                              str(_tag(record, "Make")) if _tag(record, "Make") else None,
                              str(_tag(record, "Model")) if _tag(record, "Model") else None,
                              tuple(warnings))
