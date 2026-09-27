from collections import defaultdict

from .clustering import haversine_km
from .config import SEQUENCE_MAX_DISTANCE_KM, SEQUENCE_MAX_GAP_HOURS
from .models import DayGroup, SequenceSegment


def build_day_groups(events):
    by_day = defaultdict(list)
    for event in events:
        by_day[event.resolved_date].append(event)
    groups = []
    for day in sorted(by_day):
        items = sorted(by_day[day], key=lambda e: (e.capture_datetime is None, e.capture_datetime, e.event_id))
        timed = [event for event in items if event.capture_datetime is not None and event.capture_datetime_source != "ArchiveDayFolder"]
        sequences, current = [], []
        for event in timed:
            if current:
                previous = current[-1]
                hours = (event.capture_datetime.replace(tzinfo=None) - previous.capture_datetime.replace(tzinfo=None)).total_seconds() / 3600
                distance = haversine_km(previous.latitude, previous.longitude, event.latitude, event.longitude)
                if hours < 0 or hours > SEQUENCE_MAX_GAP_HOURS or distance > SEQUENCE_MAX_DISTANCE_KM:
                    if len(current) >= 2:
                        sequences.append(SequenceSegment(day, tuple(e.event_id for e in current)))
                    current = []
            current.append(event)
        if len(current) >= 2:
            sequences.append(SequenceSegment(day, tuple(e.event_id for e in current)))
        altitudes = [e.altitude_m for e in items if e.altitude_m is not None]
        groups.append(DayGroup(day, len(items),
                               (min(e.latitude for e in items), min(e.longitude for e in items),
                                max(e.latitude for e in items), max(e.longitude for e in items)),
                               min(altitudes) if altitudes else None, max(altitudes) if altitudes else None,
                               tuple(sequences)))
    return groups
