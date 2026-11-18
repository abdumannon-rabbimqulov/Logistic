"""Buyurtma statusi o'zgargan har bir joyda `order.status_changed` hodisasi chiqishi."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from order import crud as order_crud
from order.models import OrderStatus
from services import queue


@pytest.fixture
def published(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def fake_publish(event, payload):
        sent.append((event, payload))
        return True

    monkeypatch.setattr(queue, "publish_event", fake_publish)
    return sent


def _order(status=OrderStatus.PENDING):
    return SimpleNamespace(id=5, customer_id=11, driver_id=None, status=status)


def test_publish_status_changed_sends_payload(published):
    order = _order(OrderStatus.ACCEPTED)
    order.driver_id = 3
    asyncio.run(
        order_crud.publish_status_changed(order, OrderStatus.PENDING, actor_user_id=9, actor_role="driver")
    )
    assert published == [
        (
            queue.EVENT_ORDER_STATUS_CHANGED,
            {
                "order_id": 5,
                "customer_id": 11,
                "driver_id": 3,
                "old_status": "PENDING",
                "new_status": "ACCEPTED",
                "changed_by_user_id": 9,
                "changed_by_role": "driver",
            },
        )
    ]


def test_publish_status_changed_skips_when_unchanged(published):
    asyncio.run(order_crud.publish_status_changed(_order(), OrderStatus.PENDING))
    assert published == []


class _FakeDB:
    async def execute(self, _stmt):
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, obj, attribute_names=None):
        pass


def test_cancel_order_publishes_event(published):
    order = _order(OrderStatus.ACCEPTED)
    order.cancelled_at = order.cancelled_by_user_id = order.cancel_reason = None
    asyncio.run(order_crud.cancel_order(_FakeDB(), order, cancelled_by_user_id=11, reason="test"))
    assert order.status == OrderStatus.CANCELLED
    assert [(e, p["old_status"], p["new_status"]) for e, p in published] == [
        (queue.EVENT_ORDER_STATUS_CHANGED, "ACCEPTED", "CANCELLED")
    ]


def test_assign_driver_publishes_event(published):
    order = _order(OrderStatus.PENDING)

    class DB(_FakeDB):
        async def refresh(self, obj, attribute_names=None):
            obj.driver_id, obj.status = 4, OrderStatus.ACCEPTED

    asyncio.run(order_crud.assign_driver(DB(), order, 4, actor_role="staff"))
    assert [(p["new_status"], p["driver_id"], p["changed_by_role"]) for _, p in published] == [
        ("ACCEPTED", 4, "staff")
    ]
