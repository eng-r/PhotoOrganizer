from collections import Counter
from datetime import timedelta


class EventGrouper:
    def __init__(self, config):
        self.config = config

    def group(self, decisions):
        days = Counter(t.value.date() for t in decisions if t.value is not None)
        mapping, month, number, start, previous = {}, None, 0, None, None
        for day in sorted(days):
            current_month = (day.year, day.month)
            if current_month != month:
                month, number, start, previous = current_month, 0, None, None
            if days[day] <= self.config["sparse_max_files_per_day"]:
                mapping[day] = ("_sparse", "")
                previous = None
                continue
            if previous is None or day != previous + timedelta(days=1) or (day - start).days >= self.config["event_max_span_days"]:
                number += 1
                start = day
            event = f"Event{number:02d}"
            mapping[day] = ("event", event)
            previous = day
        return mapping
