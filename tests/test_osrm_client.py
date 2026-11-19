"""services/osrm_client: umumiy klient, geometriyasiz so'rov va Redis keshi."""

import base64
import json
import zlib

import httpx
import pytest

from services import osrm_client
from utils.geo import simplify_polyline

ROUTE_COORDS = [[69.28, 41.31], [69.285, 41.315], [69.29, 41.32], [69.30, 41.35]]


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value


@pytest.fixture
def osrm(monkeypatch):
    """OSRM'ni MockTransport bilan almashtiradi; kelgan so'rovlar `calls` ga yoziladi."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        route = {"distance": 12345.0, "duration": 900.0}
        if request.url.params.get("overview") != "false":
            route["geometry"] = {"type": "LineString", "coordinates": ROUTE_COORDS}
        return httpx.Response(200, json={"code": "Ok", "routes": [route]})

    monkeypatch.setattr(osrm_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    redis = FakeRedis()
    monkeypatch.setattr("services.live_location.get_redis", lambda: redis)
    return calls, redis


async def test_full_route_builds_wkt_and_display(osrm):
    calls, _ = osrm
    route = await osrm_client.get_route([(41.31, 69.28), (41.35, 69.30)])

    assert route.distance_km == 12.35
    assert route.duration_min == 15.0
    assert route.geometry_wkt == "LINESTRING (69.28 41.31, 69.285 41.315, 69.29 41.32, 69.3 41.35)"
    assert route.geometry[0] == (41.31, 69.28)
    assert route.display_geometry == simplify_polyline(route.geometry)
    assert calls[0].url.params["overview"] == "full"


async def test_without_geometry_asks_overview_false_and_skips_cache(osrm):
    calls, redis = osrm
    route = await osrm_client.get_route([(41.31, 69.28), (41.35, 69.30)], with_geometry=False)

    assert route.duration_min == 15.0
    assert calls[0].url.params["overview"] == "false"
    assert redis.data == {}


async def test_second_call_with_same_points_is_served_from_cache(osrm):
    calls, redis = osrm
    points = [(41.31, 69.28), (41.35, 69.30)]
    first = await osrm_client.get_route(points)
    second = await osrm_client.get_route(points)

    assert len(calls) == 1  # ikkinchisi OSRM'ga bormadi
    assert second.distance_km == first.distance_km
    assert second.geometry_wkt == first.geometry_wkt
    assert second.display_geometry == [tuple(p) for p in first.display_geometry]
    raw = next(iter(redis.data.values()))
    cached = json.loads(zlib.decompress(base64.b64decode(raw)))
    assert cached["wkt"].startswith("LINESTRING")


async def test_very_long_route_is_not_cached(osrm, monkeypatch):
    _, redis = osrm
    monkeypatch.setattr(osrm_client, "ROUTE_CACHE_MAX_BYTES", 10)
    await osrm_client.get_route([(41.31, 69.28), (41.35, 69.30)])
    assert redis.data == {}


async def test_redis_failure_does_not_break_routing(osrm, monkeypatch):
    calls, _ = osrm

    class Broken:
        async def get(self, key):
            raise ConnectionError("redis yo'q")

        async def set(self, key, value, ex=None):
            raise ConnectionError("redis yo'q")

    monkeypatch.setattr("services.live_location.get_redis", lambda: Broken())
    route = await osrm_client.get_route([(41.31, 69.28), (41.35, 69.30)])
    assert route.distance_km == 12.35 and len(calls) == 1


async def test_no_route_raises_no_route_error(monkeypatch):
    monkeypatch.setattr(
        osrm_client,
        "_client",
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": "NoRoute"}))),
    )
    monkeypatch.setattr("services.live_location.get_redis", lambda: FakeRedis())
    with pytest.raises(osrm_client.OSRMNoRouteError):
        await osrm_client.get_route([(41.31, 69.28), (41.35, 69.30)])
