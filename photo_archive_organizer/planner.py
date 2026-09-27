from collections import defaultdict
from datetime import datetime
from pathlib import PurePosixPath

from .day_classifier import DayClassifier
from .models import PlannedMediaFile
from .safety import SafetyError, safe_name


MONTH_FOLDERS = {
    1: "01-Jan", 2: "02-Feb", 3: "03-Mar", 4: "04-Apr",
    5: "05-May", 6: "06-Jun", 7: "07-Jul", 8: "08-Aug",
    9: "09-Sep", 10: "10-Oct", 11: "11-Nov", 12: "12-Dec",
}


def storage_leaf_for(media):
    return "CR2" if media.path.suffix.lower() == ".cr2" else ""


class ArchivePlanner:
    def __init__(self, grouping):
        self.classifier = DayClassifier(grouping)

    @staticmethod
    def _base_destination(timestamp, classifications):
        if timestamp.value is None:
            return "_UNKNOWN_DATE", "UNKNOWN_DATE", 0, "", ""
        day = timestamp.value.date()
        classification, count = classifications[day]
        month_folder = MONTH_FOLDERS[day.month]
        day_folder = f"Day{day.day:02d}" if classification == "DAY_FOLDER" else "_sparse"
        return f"{day.year:04d}/{month_folder}/{day_folder}", classification, count, month_folder, day_folder

    def build(self, media, timestamps):
        primary_media = [item for item in media if item.media_role == "PRIMARY_MEDIA"]
        classifications = self.classifier.classify(primary_media, timestamps)
        plans = []
        primary_plans = {}
        for item in primary_media:
            if not safe_name(item.path.name):
                raise SafetyError(f"unsafe destination filename: {item.relative_path}")
            timestamp = timestamps[item.relative_path]
            base, classification, count, month_folder, day_folder = self._base_destination(timestamp, classifications)
            storage_leaf = storage_leaf_for(item)
            folder = f"{base}/{storage_leaf}" if storage_leaf else base
            entry = PlannedMediaFile(item, timestamp, f"{folder}/{item.path.name}", classification, count,
                                     month_folder, day_folder, item.media_role, storage_leaf)
            plans.append(entry)
            primary_plans[item.relative_path] = entry
        for item in (item for item in media if item.media_role == "SIDECAR"):
            primary = primary_plans[item.associated_primary]
            folder = primary.destination.rsplit("/", 1)[0]
            plans.append(PlannedMediaFile(item, primary.timestamp, f"{folder}/{item.path.name}",
                                          primary.day_classification, primary.daily_primary_media_count,
                                          primary.month_folder, primary.day_folder, item.media_role,
                                          primary.storage_leaf, item.associated_primary))
        plans.sort(key=lambda p: (p.timestamp.value is None,
                                 p.timestamp.value.replace(tzinfo=None) if p.timestamp.value else datetime.max,
                                 p.media.relative_path.casefold(), p.media.relative_path))
        return plans

    @staticmethod
    def validate(plan, eligible):
        if len(plan) != len(eligible) or {p.media.relative_path for p in plan} != {f.relative_path for f in eligible}:
            raise SafetyError("plan does not cover every eligible file exactly once")
        destinations = defaultdict(list)
        for entry in plan:
            path = PurePosixPath(entry.destination)
            if path.is_absolute() or ".." in path.parts or path.parts[0] == "_process" or not all(safe_name(x) for x in path.parts):
                raise SafetyError("invalid destination path in plan")
            destinations[entry.destination.casefold()].append(entry.media.relative_path)
        return {name for group in destinations.values() if len(group) > 1 for name in group}
