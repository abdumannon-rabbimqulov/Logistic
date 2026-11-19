"""Buyurtma statusi o'zgargan har bir joyda `order.status_changed` hodisasi outbox'ga
(biznes o'zgarishi bilan bitta tranzaksiyada, commit'dan OLDIN) yoziladi."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from order import crud as order_crud
from order.models import OrderStatus
from services import queue
from services.outbox import OutboxEvent


class _FakeDB:
    def __init__(self):
        self.added: list = []
        self.committed_with: list[list] = []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, _stmt):
        # `UPDATE ... RETURNING driver_id` (bekor qilingan takliflar) — bo'sh.
        return SimpleNamespace(rowcount=1, scalars=lambda: SimpleNamespace(all=lambda: []))

    async def commit(self):
        # Commit paytida qaysi hodisalar sessiyada bo'lganini eslab qolamiz.
        self.committed_with.append(list(self.added))

    async def rollback(self):
        pass

    async def refresh(self, obj, attribute_names=None):
        pass

    def events(self):
        return [o for o in self.added if isinstance(o, OutboxEvent)]


def _order(status=OrderStatus.PENDING):
    return SimpleNamespace(id=5, customer_id=11, driver_id=None, status=status)


def test_record_status_changed_payload():
    db = _FakeDB()
    order = _order(OrderStatus.ACCEPTED)
    order.driver_id = 3
    order_crud.record_order_status_changed(db, order, OrderStatus.PENDING, actor_user_id=9, actor_role="driver")
    [row] = db.events()
    assert row.event == queue.EVENT_ORDER_STATUS_CHANGED
    assert row.envelope["event"] == queue.EVENT_ORDER_STATUS_CHANGED
    assert row.envelope["event_id"] == row.event_id
    assert row.envelope["data"] == {
        "order_id": 5,
        "customer_id": 11,
        "driver_id": 3,
        "old_status": "PENDING",
        "new_status": "ACCEPTED",
        "changed_by_user_id": 9,
        "changed_by_role": "driver",
    }


def test_record_status_changed_skips_when_unchanged():
    db = _FakeDB()
    order_crud.record_order_status_changed(db, _order(), OrderStatus.PENDING)
    assert db.events() == []


def test_cancel_order_writes_event_in_same_transaction():
    db = _FakeDB()
    order = _order(OrderStatus.ACCEPTED)
    order.cancelled_at = order.cancelled_by_user_id = order.cancel_reason = None
    asyncio.run(order_crud.cancel_order(db, order, cancelled_by_user_id=11, reason="test"))
    assert order.status == OrderStatus.CANCELLED
    [row] = db.events()
    assert (row.envelope["data"]["old_status"], row.envelope["data"]["new_status"]) == ("ACCEPTED", "CANCELLED")
    # Hodisa commit'dan OLDIN sessiyada bo'lgan — ya'ni o'zgarish bilan birga saqlanadi.
    assert row in db.committed_with[-1]


def test_assign_driver_writes_event():
    db = _FakeDB()
    order = _order(OrderStatus.PENDING)
    asyncio.run(order_crud.assign_driver(db, order, 4, actor_role="staff"))
    [row] = db.events()
    data = row.envelope["data"]
    assert (data["new_status"], data["driver_id"], data["changed_by_role"]) == ("ACCEPTED", 4, "staff")
    assert row in db.committed_with[-1]
