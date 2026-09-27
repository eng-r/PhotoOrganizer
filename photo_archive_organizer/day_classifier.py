from collections import Counter


class DayClassifier:
    def __init__(self, config):
        self.threshold = config["threshold"]

    def classify(self, primary_media, timestamps):
        counts = Counter(
            timestamps[media.relative_path].value.date()
            for media in primary_media
            if timestamps[media.relative_path].value is not None
        )
        return {
            day: ("DAY_FOLDER" if count >= self.threshold else "SPARSE", count)
            for day, count in counts.items()
        }
