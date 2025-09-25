from travel_times import InterfaceTravelTimeEngine
from travel_times import dinnerCache

from ratelimiter import RateLimiter
from requests import post
from geocoder import osm as osm_geocode

from typing import TypedDict, Tuple, Any

import json

import datetime


class OsmPoint(TypedDict):
    pos: Tuple[float, float]
    osm: Any


class MotisTravelTimeEngine(InterfaceTravelTimeEngine[OsmPoint]):
    def __init__(self):
        pass

    def name(self):
        return "MotisClient"

    def __repr__(self):
        # required for percache
        return "MotisTravelEngine"

    @dinnerCache
    def route_between_points(
        self,
        start: OsmPoint,
        dest: OsmPoint,
        time: datetime.datetime = datetime.datetime.now(),
    ) -> int:
        arrival_window_start = time - datetime.timedelta(minutes=10)
        arrival_window_end = time + datetime.timedelta(minutes=1)

        request_data = {
            "destination": {"type": "Module", "target": "/intermodal"},
            "content_type": "IntermodalRoutingRequest",
            "content": {
                "start_type": "IntermodalPretripStart",
                "start": {  # SearchDirection reverse is on => start & stop swapped
                    "position": {
                        "lat": dest["pos"][0],
                        "lng": dest["pos"][1],
                    },
                    "interval": {
                        "begin": int(round(arrival_window_start.timestamp())),
                        "end": int(round(arrival_window_end.timestamp())),
                    },
                    "min_connection_count": 1,
                    "extend_interval_earlier": True,
                    "extend_interval_later": False,
                },
                "start_modes": [
                    {
                        "mode_type": "FootPPR",
                        "mode": {
                            "search_options": {
                                "profile": "default",
                                "duration_limit": 900,
                            }
                        },
                    }
                ],
                "destination_type": "InputPosition",
                "destination": {"lat": start["pos"][0], "lng": start["pos"][1]},
                "destination_modes": [
                    {
                        "mode_type": "FootPPR",
                        "mode": {
                            "search_options": {
                                "profile": "default",
                                "duration_limit": 900,
                            }
                        },
                    }
                ],
                "search_type": "Default",
                "search_dir": "Backward",
            },
        }

        # must rate limit if not self-hostet
        url = "http://localhost:8080/"
        result_json = post(url, data=json.dumps(request_data)).json()

        trip = result_json["content"]["connections"][-1]
        start_time = datetime.datetime.fromtimestamp(
            trip["stops"][0]["departure"]["time"]
        )
        dest_time = datetime.datetime.fromtimestamp(
            trip["stops"][-1]["arrival"]["time"]
        )

        duration = dest_time - start_time
        return int(duration.total_seconds() / 60)

    @dinnerCache
    @RateLimiter(max_calls=1, period=1)
    def get_geo(self, address: str) -> OsmPoint:
        geo = osm_geocode(address)
        if geo.latlng is None:
            print("Error: Could not find", address)
            exit(-1)

        return {"pos": (geo.latlng[0], geo.latlng[1]), "osm": geo.osm}
