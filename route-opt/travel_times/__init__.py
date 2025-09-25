import datetime
from math import radians, cos, sin, asin, sqrt
from typing import TypeVar, Generic


import os
import percache
import tempfile

GeoPoint = TypeVar("GeoPoint")

cache_path = os.path.join(tempfile.gettempdir(), "dinner-plan-cache")
dinnerCache = percache.Cache(cache_path, livesync=True)


class InterfaceTravelTimeEngine(Generic[GeoPoint]):
    def name(self) -> str:
        pass

    def route_between_points(
        self, start: GeoPoint, dest: GeoPoint, time: datetime.datetime
    ) -> int:
        pass

    def get_geo(self, address: str) -> GeoPoint:
        pass


def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371  # Radius of earth in kilometers. Use 3956 for miles
    return c * r
