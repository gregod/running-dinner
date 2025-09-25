from travel_times import InterfaceTravelTimeEngine, haversine
from travel_times import dinnerCache

from pyhafas import HafasClient
from pyhafas.profile import DBProfile
from pyhafas.types.fptf import Station

from ratelimiter import RateLimiter

import datetime


class HafasTravelTimeEngine(InterfaceTravelTimeEngine[Station]):
    def __init__(self):
        self.hafas_client = HafasClient(DBProfile())

    def name(self):
        return "HafasClient"

    def __repr__(self):
        # required for percache
        return "HafasTravelEngine"

    @dinnerCache
    @RateLimiter(max_calls=1, period=20)
    def route_between_points(
        self,
        start: Station,
        dest: Station,
        time: datetime.datetime = datetime.datetime.now(),
    ) -> int:
        direct_distance = haversine(
            start.longitude, start.latitude, dest.longitude, dest.latitude
        )
        if direct_distance < 0.8:
            return direct_distance * 11

        if start.lid == dest.lid:
            return 0
        routes = self.hafas_client.journeys(start.lid, dest.lid, time)
        route = routes[0]
        return int(route.duration.seconds / 60)

    @dinnerCache
    @RateLimiter(max_calls=1, period=10)
    def get_geo(self, address: str) -> Station:
        results = self.hafas_client.locations(address, "ALL")
        if len(results) == 0:
            print("Error: Could not find ", address)
            exit(2)
        return results[0]
