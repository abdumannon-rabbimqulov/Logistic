"""Outbox: JSON'ga yaroqli payload va relay xulqi (broker xatosida yozuv qoladi)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from order.models import OrderStatus
from services import outbox, queue


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
        self.commits = 0
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, _stmt):
        return _Rows(self.rows)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def test_enqueue_makes_payload_jsonable():
    db = _DB([])
    row = outbox.enqueue(
        db, "order.status_changed", {"price": Decimal("10.5"), "status": OrderStatus.PENDING, "at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    )
    assert db.added == [row]
    assert row.envelope["data"] == {"price": "10.5", "status": "PENDING", "at": "2026-01-01 00:00:00+00:00"}


def _row(i):
    return SimpleNamespace(id=i, event="order.status_changed", envelope={"event": "order.status_changed", "event_id": str(i)},
                           attempts=0, published_at=None, last_error=None)


def test_relay_marks_published(monkeypatch):
    sent = []

    async def fake_publish(envelope):
        sent.append(envelope["event_id"])

    monkeypatch.setattr(queue, "publish_envelope", fake_publish)
    rows = [_row(1), _row(2)]
    db = _DB(rows)
    assert asyncio.run(outbox.relay_once(db)) == 2
    assert sent == ["1", "2"]
    assert all(r.published_at is not None for r in rows)
    assert db.commits == 1


def test_relay_keeps_row_when_broker_down(monkeypatch):
    async def failing(_envelope):
        raise queue.QueueUnavailable("broker o'chiq")

    monkeypatch.setattr(queue, "publish_envelope", failing)
    rows = [_row(1), _row(2)]
    db = _DB(rows)
    assert asyncio.run(outbox.relay_once(db)) == 0
    assert rows[0].published_at is None and rows[0].attempts == 1 and "broker" in rows[0].last_error
    # Birinchisi yiqilsa qolganlariga urinilmaydi (keyingi aylanishda qayta).
    assert rows[1].attempts == 0
