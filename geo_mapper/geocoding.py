import json
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class PlaceInfo:
    place_name: str
    admin1: str | None = None
    country: str | None = None
    country_code: str | None = None


class GeoNamesGeocoder:
    provider = "geonames"

    def __init__(self, username, timeout=8):
        self.username, self.timeout = username, timeout

    def lookup(self, latitude, longitude):
        query = urlencode({"lat": latitude, "lng": longitude, "username": self.username})
        with urlopen("https://secure.geonames.org/findNearbyPlaceNameJSON?" + query, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        rows = data.get("geonames", [])
        if not rows:
            return None
        row = rows[0]
        name = row.get("name")
        return PlaceInfo(str(name), row.get("adminName1"), row.get("countryName"), row.get("countryCode")) if name else None
