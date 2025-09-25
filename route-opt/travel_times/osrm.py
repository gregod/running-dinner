from travel_times import InterfaceTravelTimeEngine
from travel_times import dinnerCache

import datetime
import geocoder

import requests

from typing import TypedDict, Tuple, Any
from ratelimiter import RateLimiter


class OsrmPoint(TypedDict):
    pos: Tuple[float, float]
    osm: Any


class OsrmTravelTimeEngine(InterfaceTravelTimeEngine[OsrmPoint]):
    def __repr__(self):
        # required for percache
        return "OsrmTravelEngine"

    @dinnerCache
    def route_between_points(
        self,
        start: OsrmPoint,
        dest: OsrmPoint,
        time: datetime.datetime = datetime.datetime.now(),
    ) -> int:
        url = f"http://localhost:5000/route/v1/driving/{start['pos'][1]},{start['pos'][0]};{dest['pos'][1]},{dest['pos'][0]}?overview=false"
        result_json = requests.get(url).json()
        return int(result_json["routes"][0]["duration"] / 60)

    def name(self):
        return "Osrm"

    @dinnerCache
    @RateLimiter(max_calls=1, period=1)
    def get_geo(self, address: str) -> OsrmPoint:
        geo = geocoder.osm(address)
        return {"pos": (geo.latlng[0], geo.latlng[1]), "osm": geo.osm}
