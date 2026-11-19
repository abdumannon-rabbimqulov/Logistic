"""Haydovchiga "taklif o'zgardi" signali: core → Redis → tracking_service WS."""

import json
import time

import fakeredis
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from contracts import redis_keys
from services import dispatch_signal


class RecordingRedis:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


async def test_notify_drivers_publishes_once_per_driver(monkeypatch):
    redis = RecordingRedis()
    monkeypatch.setattr("services.live_location.get_redis", lambda: redis)

    await dispatch_signal.notify_drivers([7, None, 7, 9])

    assert sorted(ch for ch, _ in redis.published) == ["driver_dispatch_ch:7", "driver_dispatch_ch:9"]
    assert all(json.loads(p) == {"event": "dispatch_changed"} for _, p in redis.published)


async def test_notify_drivers_survives_redis_failure(monkeypatch):
    class Broken:
        async def publish(self, *_):
            raise ConnectionError("redis yo'q")

    monkeypatch.setattr("services.live_location.get_redis", lambda: Broken())
    await dispatch_signal.notify_drivers([1])  # xato tashlamaydi


async def test_notify_drivers_noop_without_ids(monkeypatch):
    monkeypatch.setattr("services.live_location.get_redis", lambda: pytest.fail("chaqirilmasligi kerak"))
    await dispatch_signal.notify_drivers([None])


# ── tracking_service WS ──────────────────────────────────────────────────────────


@pytest.fixture
def tracking(monkeypatch):
    from tracking_service import core_client, main, store

    server = fakeredis.FakeServer()
    monkeypatch.setattr(store, "_redis", fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))

    async def identity(token):
        return {"driver_id": 42, "user_id": 1} if token == "good" else None

    monkeypatch.setattr(core_client, "driver_identity", identity)
    return TestClient(main.app), fakeredis.FakeRedis(server=server)


def test_dispatch_ws_rejects_bad_token(tracking):
    client, _ = tracking
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/drivers/ws/dispatch?token=bad") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_dispatch_ws_forwards_signal_for_this_driver_only(tracking):
    client, publisher = tracking
    with client.websocket_connect("/api/drivers/ws/dispatch?token=good") as ws:
        assert ws.receive_json() == {"event": "connected"}
        # Boshqa haydovchining signali kelmasligi kerak, o'ziniki kelishi kerak.
        publisher.publish(redis_keys.driver_dispatch_channel(99), json.dumps({"event": "dispatch_changed"}))
        deadline = time.time() + 2
        while publisher.pubsub_numsub(redis_keys.driver_dispatch_channel(42))[0][1] == 0 and time.time() < deadline:
            time.sleep(0.01)
        publisher.publish(redis_keys.driver_dispatch_channel(42), json.dumps({"event": "dispatch_changed"}))
        assert ws.receive_json() == {"event": "dispatch_changed"}
