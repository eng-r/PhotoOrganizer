from collections import defaultdict
from datetime import datetime
from pathlib import PurePosixPath

from .event_grouper import EventGrouper
from .models import PlannedMediaFile
from .safety import SafetyError, safe_name


class ArchivePlanner:
    def __init__(self, grouping):
        self.grouper = EventGrouper(grouping)

    def build(self, media, timestamps):
        grouping = self.grouper.group(timestamps.values())
        plans = []
        for item in media:
            if not safe_name(item.path.name):
                raise SafetyError(f"unsafe destination filename: {item.relative_path}")
            timestamp = timestamps[item.relative_path]
            if timestamp.value is None:
                folder, classification, event = "_UNKNOWN_DATE", "unknown", ""
            else:
                day = timestamp.value.date()
                classification, event = grouping[day]
                folder = f"{day.year:04d}/{day.month:02d}/{event or '_sparse'}"
            plans.append(PlannedMediaFile(item, timestamp, f"{folder}/{item.path.name}", classification, event))
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
