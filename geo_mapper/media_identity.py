import hashlib
from collections import defaultdict
from pathlib import Path

from .config import PREVIEWABLE_EXTENSIONS, RAW_EXTENSIONS
from .models import GeoPhotoEvent, NormalizedMetadata


class MediaIdentityResolver:
    def resolve(self, month_root: Path, files: list[Path], metadata: dict[Path, NormalizedMetadata]):
        grouped = defaultdict(list)
        for path in files:
            scope = path.parent.parent if path.suffix.lower() in RAW_EXTENSIONS and path.parent.name.casefold() == "cr2" else path.parent
            grouped[(scope, path.stem.casefold())].append(path)
        events, warnings = [], []
        for key in sorted(grouped, key=lambda k: (str(k[0]).casefold(), k[1])):
            related = sorted(grouped[key], key=lambda p: (self._priority(p), p.name.casefold(), p.name))
            representative = related[0]
            candidates = [metadata[p] for p in related]
            selected = next((m for m in candidates if m.latitude is not None and m.longitude is not None), metadata[representative])
            dated = next((m for m in candidates if m.resolved_date is not None), selected)
            if selected.latitude is None or selected.longitude is None:
                continue
            if dated.resolved_date is None:
                warnings.append((representative, "geotagged media has no resolved date"))
                continue
            identity = representative.relative_to(month_root).as_posix().casefold() + "|" + dated.resolved_date.isoformat()
            event_id = "photo-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            events.append(GeoPhotoEvent(event_id, representative, tuple(related), representative.name,
                                        dated.resolved_date, dated.capture_datetime, dated.capture_datetime_source,
                                        selected.latitude, selected.longitude, selected.altitude_m,
                                        selected.make, selected.model))
        events.sort(key=lambda e: (e.resolved_date, e.capture_datetime.replace(tzinfo=None) if e.capture_datetime else datetime_max(),
                                   e.representative_path.as_posix().casefold(), e.representative_path.as_posix()))
        return events, warnings, len(grouped)

    @staticmethod
    def _priority(path):
        extension = path.suffix.lower()
        return 0 if extension in PREVIEWABLE_EXTENSIONS else 2 if extension in RAW_EXTENSIONS else 1


def datetime_max():
    from datetime import datetime
    return datetime.max
