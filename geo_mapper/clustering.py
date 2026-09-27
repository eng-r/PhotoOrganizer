import hashlib
import math

from .config import PLACE_CLUSTER_RADIUS_KM
from .models import GeoCluster


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def cluster_events(events, radius_km=PLACE_CLUSTER_RADIUS_KM):
    clusters = []
    for event in sorted(events, key=lambda e: (e.latitude, e.longitude, e.event_id)):
        match = next((items for items in clusters
                      if haversine_km(sum(e.latitude for e in items) / len(items), sum(e.longitude for e in items) / len(items),
                                      event.latitude, event.longitude) <= radius_km), None)
        if match is None:
            clusters.append([event])
        else:
            match.append(event)
    result = []
    for items in clusters:
        items.sort(key=lambda e: e.event_id)
        lat = sum(e.latitude for e in items) / len(items)
        lon = sum(e.longitude for e in items) / len(items)
        digest = hashlib.sha256("|".join(e.event_id for e in items).encode()).hexdigest()[:12]
        result.append(GeoCluster(f"place-{digest}", lat, lon, tuple(e.event_id for e in items)))
    return sorted(result, key=lambda c: (c.latitude, c.longitude, c.cluster_id))
