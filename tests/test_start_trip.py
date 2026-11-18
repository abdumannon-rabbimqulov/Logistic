""""Start" tugmasi: qoida, idempotentlik va eslatmalar jadvali."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from order.models import OrderStatus
from services import order_flow, queue
from services.outbox import OutboxEvent
from notification_service.handlers.orders import sender_message_for
from services.start_reminders import reminder_for


class _DB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj, attribute_names=None):
        pass


def _order(status=OrderStatus.ACCEPTED, started_at=None):
    return SimpleNamespace(
        id=9, customer_id=1, driver_id=2, status=status, started_at=started_at,
        departure_at=None, pickup_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )


def test_start_trip_sets_time_and_emits_event():
    db, order = _DB(), _order()
    asyncio.run(order_flow.start_trip(db, order, actor_user_id=77))
    assert order.started_at is not None
    events = [o.event for o in db.added if isinstance(o, OutboxEvent)]
    assert events == [queue.EVENT_ORDER_TRIP_STARTED]


def test_start_trip_on_scheduled_moves_to_accepted():
    db, order = _DB(), _order(OrderStatus.SCHEDULED)
    asyncio.run(order_flow.start_trip(db, order))
    assert order.status == OrderStatus.ACCEPTED
    events = [o.event for o in db.added if isinstance(o, OutboxEvent)]
    assert events == [queue.EVENT_ORDER_STATUS_CHANGED, queue.EVENT_ORDER_TRIP_STARTED]


def test_start_trip_is_idempotent_and_guarded():
    db = _DB()
    started = _order(started_at=datetime.now(timezone.utc))
    asyncio.run(order_flow.start_trip(db, started))
    assert db.added == []
    with pytest.raises(order_flow.TripStartError):
        asyncio.run(order_flow.start_trip(db, _order(OrderStatus.PENDING)))


def test_sender_gets_trip_started_message():
    text = sender_message_for(queue.EVENT_ORDER_TRIP_STARTED, {"order_id": 9, "customer_id": 1})
    assert text and "yo'lga chiqdi" in text


DEP = datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "before, key, staff",
    [
        (timedelta(hours=30), None, False),
        (timedelta(hours=20), "d1", False),
        (timedelta(hours=1), "h2", False),
        (timedelta(minutes=10), "m30", False),
        (timedelta(minutes=-5), "late0", False),
        (timedelta(minutes=-20), "late1", False),
        (timedelta(minutes=-35), "late2", True),
    ],
)
def test_reminder_schedule(before, key, staff):
    r = reminder_for(9, DEP, DEP - before)
    if key is None:
        assert r is None
    else:
        assert r.key == key and r.notify_staff is staff and "#9" in r.text
