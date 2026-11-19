"""`order.*` hodisalarini iste'mol qilish (bazaga yozish) va hodisa shartnomasi."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from chat_service import domain, queue
from chat_service.db import session_factory
from chat_service.events import handle_order_event
from chat_service.models import Conversation

from .conftest import DRIVER_ID, DRIVER_USER, SENDER

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def status_event(status, at, **extra):
    data = {
        "order_id": 9,
        "customer_id": SENDER,
        "driver_id": DRIVER_ID,
        "old_status": "PENDING",
        "new_status": status,
        "changed_by_user_id": None,
        "changed_by_role": None,
        **extra,
    }
    return domain.EVENT_ORDER_STATUS_CHANGED, data, at


async def load(order_id=9):
    async with session_factory()() as db:
        return (await db.execute(select(Conversation).where(Conversation.order_id == order_id))).scalar_one_or_none()


async def test_lifecycle(chat_env):
    assert await handle_order_event(*status_event("PENDING", T0)) is None
    assert await load() is None

    await handle_order_event(*status_event("ACCEPTED", T0 + timedelta(minutes=1)))
    conv = await load()
    assert conv.sender_user_id == SENDER and conv.driver_id == DRIVER_ID and conv.driver_user_id is None

    await handle_order_event(*status_event("IN_PROGRESS", T0 + timedelta(minutes=30), driver_user_id=DRIVER_USER))
    conv = await load()
    assert conv.driver_user_id == DRIVER_USER and conv.order_status == "IN_PROGRESS"

    await handle_order_event(*status_event("COMPLETED", T0 + timedelta(hours=2)))
    conv = await load()
    assert domain.as_utc(conv.readonly_at) == T0 + timedelta(hours=26)

    # Kechikib kelgan eski hodisa holatni buzmaydi.
    await handle_order_event(*status_event("ACCEPTED", T0 + timedelta(minutes=2)))
    assert (await load()).readonly_at is not None

    # Ishtirokchilarga sahifani yangilash signali.
    updates = [(uid, e) for uid, e in chat_env["broadcaster"].sent if e["type"] == "conversation.updated"]
    assert updates and all(e["order_id"] == 9 for _, e in updates)


async def test_truck_assigned_payload(chat_env):
    # manager/router.py assign_truck payload'i.
    data = {
        "order_id": 9,
        "customer_id": SENDER,
        "driver_id": DRIVER_ID,
        "truck_number": "01A123BC",
        "truck_type_id": 3,
        "assigned_by_user_id": 1,
        "assigned_by_role": "manager",
    }
    await handle_order_event(domain.EVENT_ORDER_TRUCK_ASSIGNED, data, T0)
    conv = await load()
    assert conv is not None and conv.driver_id == DRIVER_ID and conv.status == "open"


async def test_duplicate_delivery_is_idempotent(chat_env):
    for _ in range(3):
        await handle_order_event(*status_event("ACCEPTED", T0))
    async with session_factory()() as db:
        rows = (await db.execute(select(Conversation))).scalars().all()
    assert len(rows) == 1


def test_envelope_parsing():
    envelope = queue.build_event("order.status_changed", {"order_id": 1, "new_status": "ACCEPTED"})
    event, data, occurred_at = queue.parse_envelope(json.dumps(envelope).encode())
    assert event == "order.status_changed" and data["order_id"] == 1
    assert occurred_at is not None and occurred_at.tzinfo is not None


def test_contract_with_core():
    """Routing key va exchange core (`services/queue.py`) bilan bir xil bo'lishi shart."""
    from services import queue as core_queue

    assert queue.EVENTS_EXCHANGE == core_queue.EVENTS_EXCHANGE
    assert queue.EVENT_ORDER_STATUS_CHANGED == core_queue.EVENT_ORDER_STATUS_CHANGED
    assert queue.EVENT_ORDER_TRUCK_ASSIGNED == core_queue.EVENT_ORDER_TRUCK_ASSIGNED
    assert queue.CHAT_ORDER_EVENTS_PATTERN == "order.*"
    assert queue.CHAT_NOTIFICATIONS_PATTERN == "chat.*"
    prefix, _, rest = queue.EVENT_CHAT_MESSAGE_CREATED.partition(".")
    assert prefix == "chat" and "." not in rest
