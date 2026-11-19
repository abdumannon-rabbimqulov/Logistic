"""Buyurtma sahifasiga "buyurtma o'zgardi" signali: core → Redis → tracking_service WS."""

import asyncio
import json
import time
from types import SimpleNamespace

import fakeredis
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from contracts import redis_keys
from services import order_signal, outbox, queue


class RecordingRedis:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


async def test_notify_orders_publishes_once_per_order(monkeypatch):
    redis = RecordingRedis()
    monkeypatch.setattr("services.live_location.get_redis", lambda: redis)

    await order_signal.notify_orders([5, None, 5, 8])

    assert sorted(ch for ch, _ in redis.published) == ["order_updates_ch:5", "order_updates_ch:8"]
    assert all(json.loads(p) == {"event": "order_changed"} for _, p in redis.published)


async def test_notify_orders_survives_redis_failure_and_noop(monkeypatch):
    class Broken:
        async def publish(self, *_):
            raise ConnectionError("redis yo'q")

    monkeypatch.setattr("services.live_location.get_redis", lambda: Broken())
    await order_signal.notify_orders([1])  # xato tashlamaydi

    monkeypatch.setattr("services.live_location.get_redis", lambda: pytest.fail("chaqirilmasligi kerak"))
    await order_signal.notify_orders([])
    await order_signal.notify_orders([None])


# ── outbox relay signal beradi ───────────────────────────────────────────────────


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return _Rows(self.rows)

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _row(i, data):
    return SimpleNamespace(
        id=i,
        event="order.status_changed",
        envelope={"event": "order.status_changed", "event_id": str(i), "data": data},
        attempts=0,
        published_at=None,
        last_error=None,
    )


def test_relay_signals_orders_of_published_events(monkeypatch):
    signalled = []

    async def fake_publish(_envelope):
        return None

    async def fake_notify(ids):
        signalled.append(sorted(ids))

    monkeypatch.setattr(queue, "publish_envelope", fake_publish)
    monkeypatch.setattr(order_signal, "notify_orders", fake_notify)
    rows = [_row(1, {"order_id": 7}), _row(2, {"order_id": 7}), _row(3, {"order_id": 9}), _row(4, {"x": 1}), _row(5, None)]
    assert asyncio.run(outbox.relay_once(_DB(rows))) == 5
    assert signalled == [[7, 9]]  # takror va order_id'siz hodisalar signal bermaydi


def test_relay_does_not_signal_when_broker_is_down(monkeypatch):
    signalled = []

    async def failing(_envelope):
        raise queue.QueueUnavailable("broker o'chiq")

    async def fake_notify(ids):
        signalled.append(set(ids))

    monkeypatch.setattr(queue, "publish_envelope", failing)
    monkeypatch.setattr(order_signal, "notify_orders", fake_notify)
    assert asyncio.run(outbox.relay_once(_DB([_row(1, {"order_id": 7})]))) == 0
    assert signalled == [set()]  # hech narsa yuborilmagan — bo'sh to'plam


# ── tracking_service WS ──────────────────────────────────────────────────────────


@pytest.fixture
def tracking(monkeypatch):
    from tracking_service import core_client, main, store

    server = fakeredis.FakeServer()
    monkeypatch.setattr(store, "_redis", fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))

    async def access(token, order_id):
        return {"order_id": order_id, "driver_id": None, "status": "PENDING"} if token == "good" else None

    monkeypatch.setattr(core_client, "order_access", access)
    return TestClient(main.app), fakeredis.FakeRedis(server=server)


def test_order_ws_rejects_without_access(tracking):
    client, _ = tracking
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/orders/5/ws/updates?token=bad") as ws:
            ws.receive_json()
    assert exc.value.code == 4403


def test_order_ws_works_before_driver_is_assigned_and_filters_by_order(tracking):
    """Haydovchi hali yo'q (`driver_id=None`) — `driver-location` WS bu holatda yopilardi,
    `updates` esa ishlashi kerak: qidiruv paytida ham sahifa jonli yangilanadi."""
    client, publisher = tracking
    with client.websocket_connect("/api/orders/5/ws/updates?token=good") as ws:
        assert ws.receive_json() == {"event": "connected"}
        publisher.publish(redis_keys.order_updates_channel(6), json.dumps({"event": "order_changed"}))
        deadline = time.time() + 2
        while publisher.pubsub_numsub(redis_keys.order_updates_channel(5))[0][1] == 0 and time.time() < deadline:
            time.sleep(0.01)
        publisher.publish(redis_keys.order_updates_channel(5), json.dumps({"event": "order_changed"}))
        assert ws.receive_json() == {"event": "order_changed"}
