import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import ResolvedTimestamp


# Group-qualified common standards, independent of camera Make/Model and filename prefix.
TAG_MAP = {
    "DateTimeOriginal": ["ExifIFD:DateTimeOriginal", "EXIF:DateTimeOriginal", "IFD0:DateTimeOriginal", "XMP-exif:DateTimeOriginal"],
    "XMPDateCreated": ["XMP-photoshop:DateCreated", "XMP-xmp:CreateDate"],
    "CreateDate": ["ExifIFD:CreateDate", "EXIF:CreateDate", "IFD0:CreateDate", "PNG:CreationTime"],
    "VideoCreationDate": ["Keys:CreationDate", "UserData:DateTimeOriginal", "QuickTime:CreateDate",
                          "Track1:MediaCreateDate", "Track1:TrackCreateDate", "Track2:MediaCreateDate"],
}


def filename_date(name):
    stem = Path(name).stem
    formats = [
        (r"(?:IMG|VID)_(\d{8})_(\d{6})", "%Y%m%d%H%M%S", "second"),
        (r"(?:IMG|VID)(\d{8})(\d{6})(?:_\d+)?", "%Y%m%d%H%M%S", "second"),
        (r"PXL_(\d{8})_(\d{9})", "%Y%m%d%H%M%S%f", "subsecond"),
        (r"(\d{4}-\d{2}-\d{2}) (\d{2}\.\d{2}\.\d{2})", "%Y-%m-%d%H.%M.%S", "second"),
        (r"(\d{4}-\d{2}-\d{2})_(\d{6})", "%Y-%m-%d%H%M%S", "second"),
        (r"IMG-(\d{8})-WA\d+", "%Y%m%d", "day"),
        (r"Screenshot_(\d{8})-(\d{6})", "%Y%m%d%H%M%S", "second"),
    ]
    for pattern, fmt, precision in formats:
        match = re.fullmatch(pattern, stem, flags=re.IGNORECASE | re.ASCII)
        if match:
            return datetime.strptime("".join(match.groups()), fmt), precision
    return None, "unknown"


def parse_embedded(value):
    text = str(value).strip()
    text = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", text)
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]|$)", text):
        raise ValueError("not a full calendar date")
    precision = "day" if len(text) == 10 else "subsecond" if re.search(r"\d{2}:\d{2}:\d{2}\.\d", text) else "second"
    return datetime.fromisoformat(text.replace("Z", "+00:00")), precision


class TimestampResolver:
    def __init__(self, config, now):
        self.config, self.now = config, now

    def resolve(self, media, metadata):
        decision = ResolvedTimestamp()
        candidates = []
        tags = metadata.tags
        for category in self.config["priority"]:
            if category in TAG_MAP:
                mapped_tags = list(TAG_MAP[category])
                if category == "VideoCreationDate":
                    mapped_tags += sorted(k for k in tags if re.fullmatch(r"Track[0-9]+:(?:MediaCreateDate|TrackCreateDate)", k) and k not in mapped_tags)
                for tag in mapped_tags:
                    if tag in tags:
                        raw = tags[tag]
                        # Pair EXIF offset/subsecond only with the matching timestamp field.
                        suffix = "Original" if category == "DateTimeOriginal" else "Digitized"
                        if tag.startswith(("ExifIFD:", "EXIF:", "IFD0:")):
                            group = tag.split(":")[0]
                            raw = str(raw)
                            sub = tags.get(f"{group}:SubSecTime{suffix}")
                            off = tags.get(f"{group}:OffsetTime{suffix}")
                            if sub is not None and re.fullmatch(r"\d+", str(sub)) and len(raw) == 19:
                                raw += "." + str(sub)
                            if off and re.fullmatch(r"[+-]\d{2}:\d{2}", str(off)) and not re.search(r"[+-]\d{2}:\d{2}$", raw):
                                raw += str(off)
                        candidates.append((category, tag, tags[tag], raw))
            elif category == "FilenameDate":
                candidates.append((category, "FilenameDate", media.path.name, media.path.name))
            else:
                candidates.append((category, "FilesystemMTime", media.mtime_ns, media.mtime_ns))
        for category, field, original, raw in candidates:
            candidate = {"category": category, "field": field, "raw": original, "interpreted_raw": raw}
            decision.raw_candidates.append(candidate)
            try:
                if category == "FilenameDate":
                    value, precision = filename_date(raw)
                    if value is None:
                        raise ValueError("no_recognized_filename_date")
                elif category == "FilesystemMTime":
                    value, precision = datetime.fromtimestamp(raw / 1_000_000_000, timezone.utc), "subsecond"
                else:
                    value, precision = parse_embedded(raw)
                if value.year < self.config["minimum_year"]:
                    raise ValueError("before minimum_year")
                # Compare civil clocks consistently; never shift the capture calendar date.
                if value.replace(tzinfo=None) > self.now.replace(tzinfo=None) + timedelta(days=self.config["future_tolerance_days"]):
                    raise ValueError("beyond future tolerance")
                if decision.value is None:
                    confidence = "LOW" if category == "FilesystemMTime" else "MEDIUM" if category == "FilenameDate" or (category == "VideoCreationDate" and value.tzinfo is None) else "HIGH"
                    decision.value, decision.precision = value, precision
                    decision.category, decision.source_field = category, field
                    decision.confidence, decision.timezone_known = confidence, value.tzinfo is not None
            except (ValueError, OverflowError, OSError) as exc:
                decision.rejected_candidates.append({**candidate, "reason": str(exc)})
        if metadata.error:
            decision.warnings.append("metadata extraction failed: " + metadata.error)
        if decision.category == "FilesystemMTime":
            decision.warnings.append("filesystem modification time is not a capture date")
        if decision.category == "VideoCreationDate" and not decision.timezone_known:
            decision.warnings.append("video timestamp has no explicit timezone")
        if decision.value is None:
            decision.warnings.append("no usable configured timestamp; archived under _UNKNOWN_DATE")
        return decision
