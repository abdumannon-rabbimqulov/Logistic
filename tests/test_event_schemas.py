"""Core chiqaradigan hodisalar `contracts/schemas/*.json` ga mos (Go servislari ham shularga tayanadi)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from contracts.validate import validate_payload
from order import crud as order_crud
from order.models import OrderStatus
from services import order_flow, order_notices
from services.outbox import OutboxEvent


class _DB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, _stmt):
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, obj, attribute_names=None):
        pass


def _assert_valid(db):
    rows = [o for o in db.added if isinstance(o, OutboxEvent)]
    assert rows
    for row in rows:
        assert validate_payload(row.event, row.envelope["data"]) == [], row.event


def _order(status=OrderStatus.ACCEPTED, **kw):
    base = dict(id=9, customer_id=1, driver_id=2, status=status, started_at=None, departure_at=None,
                pickup_at=datetime(2026, 1, 3, tzinfo=timezone.utc))
    base.update(kw)
    return SimpleNamespace(**base)


def test_status_changed_matches_schema():
    db = _DB()
    order_crud.record_order_status_changed(db, _order(), OrderStatus.PENDING, actor_user_id=4, actor_role="driver")
    _assert_valid(db)


def test_trip_started_and_scheduled_promotion_match_schema():
    db = _DB()
    asyncio.run(order_flow.start_trip(db, _order(OrderStatus.SCHEDULED)))
    _assert_valid(db)


def test_assign_driver_matches_schema():
    db = _DB()
    asyncio.run(order_crud.assign_driver(db, _order(OrderStatus.PENDING, driver_id=None), 5, actor_role="staff"))
    _assert_valid(db)


def test_notice_matches_schema():
    db = _DB()
    order_notices.enqueue_notice(db, order_id=9, recipient_ids=[1, 2], text="Salom", kind="gps_lost")
    _assert_valid(db)


def test_validator_reports_problems():
    errors = validate_payload("order.status_changed", {"order_id": "9", "new_status": "FLYING"})
    assert any("customer_id" in e for e in errors)
    assert any("order_id" in e for e in errors)
    assert any("FLYING" in e for e in errors)
