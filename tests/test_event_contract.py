"""RabbitMQ hodisalari — xizmatlararo SHARTNOMA.

`services/queue.py` (asosiy ilova) va `support_service/queue.py` (mikroserviz)
bir xil exchange va navbatlarni e'lon qiladi. Agar biri o'zgarib, ikkinchisi
o'zgarmasa, AMQP `PRECONDITION_FAILED` bilan kanalni yopadi yoki xabarlar hech
qayerga bormay yo'qoladi — ikkalasi ham konteynerlar ko'tarilgunicha bilinmaydi.
Shu sababli nomlar shu yerda qotirilgan.

`support_service` alohida bog'liqliklarga ega, shuning uchun import qilib
bo'lmasa test o'tkazib yuboriladi (asosiy loyihaning virtualenv'ida `jose`/`asyncpg`
bo'lmasligi mumkin) — asosiy tomon baribir tekshiriladi.
"""

from __future__ import annotations

import pytest

from services import queue

EXPECTED_ROUTING_KEYS = {
    "order.status_changed",
    "order.truck_assigned",
    "support.ticket_created",
    "support.ticket_replied",
    "support.ticket_status_changed",
    "order.waypoint_changed",
    "order.trip_started",
}


def test_events_exchange_name():
    assert queue.EVENTS_EXCHANGE == "logistika.events"


def test_routing_keys_are_stable():
    actual = {
        queue.EVENT_ORDER_STATUS_CHANGED,
        queue.EVENT_ORDER_TRUCK_ASSIGNED,
        queue.EVENT_ORDER_WAYPOINT_CHANGED,
        queue.EVENT_ORDER_TRIP_STARTED,
        queue.EVENT_SUPPORT_TICKET_CREATED,
        queue.EVENT_SUPPORT_TICKET_REPLIED,
        queue.EVENT_SUPPORT_TICKET_STATUS_CHANGED,
    }
    assert actual == EXPECTED_ROUTING_KEYS


def test_queue_bindings_match_routing_keys():
    """Har bir routing key hech bo'lmasa bitta navbatga tushishi kerak.

    `order.*` va `support.*` naqshlari AMQP topic qoidasi bo'yicha bitta nuqtagacha
    bo'lgan segmentga mos keladi — kalitlarda ortiqcha nuqta bo'lsa ular hech qayerga
    bog'lanmay qolardi.
    """
    for key in EXPECTED_ROUTING_KEYS:
        prefix, _, rest = key.partition(".")
        assert "." not in rest, f"'{key}' ikkitadan ortiq segmentga ega — naqshga tushmaydi"
        assert prefix in {"order", "support"}

    assert queue.SUPPORT_EVENTS_PATTERN == "order.*"
    assert queue.SUPPORT_NOTIFICATIONS_PATTERN == "support.*"
    assert queue.SUPPORT_EVENTS_QUEUE == "support.order_events"
    assert queue.SUPPORT_NOTIFICATIONS_QUEUE == "support.notifications"
    assert queue.ORDER_NOTIFICATIONS_QUEUE == "notifications.order_events"
    assert queue.ORDER_NOTIFICATIONS_PATTERN == "order.*"


def test_dispatch_topology_untouched():
    """Mavjud dispatch navbati o'zgarmagan bo'lishi kerak — worker unga tayanadi."""
    assert queue.EXCHANGE_NAME == "logistika.dispatch"
    assert queue.JOBS_QUEUE == "dispatch.jobs"
    assert queue.DELAYED_QUEUE == "dispatch.delayed"
    assert queue.DEAD_QUEUE == "dispatch.dead"


def test_event_envelope_shape():
    envelope = queue.build_event(
        queue.EVENT_ORDER_STATUS_CHANGED, {"order_id": 7, "new_status": "completed"}
    )
    assert set(envelope) == {"event", "event_id", "occurred_at", "data"}
    assert envelope["event"] == "order.status_changed"
    assert envelope["data"]["order_id"] == 7
    # `event_id` takrorlanmasligi kerak — iste'molchi shu bilan dublikatni ajratadi.
    assert envelope["event_id"] != queue.build_event("x", {})["event_id"]


def test_support_service_uses_same_contract(monkeypatch):
    # `support_service.config` majburiy muhit o'zgaruvchilarini import paytida
    # talab qiladi (mikroserviz noto'g'ri sozlansa darhol yiqilishi uchun). Bu yerda
    # faqat konstantalar solishtiriladi, shuning uchun soxta qiymatlar yetarli.
    monkeypatch.setenv("SUPPORT_DB_URL", "postgresql+asyncpg://x:x@db:5432/support_db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    support_queue = pytest.importorskip(
        "support_service.queue",
        reason="support_service bog'liqliklari bu muhitda o'rnatilmagan",
    )

    assert support_queue.EVENTS_EXCHANGE == queue.EVENTS_EXCHANGE
    assert support_queue.SUPPORT_EVENTS_QUEUE == queue.SUPPORT_EVENTS_QUEUE
    assert support_queue.SUPPORT_NOTIFICATIONS_QUEUE == queue.SUPPORT_NOTIFICATIONS_QUEUE
    assert support_queue.SUPPORT_EVENTS_PATTERN == queue.SUPPORT_EVENTS_PATTERN
    assert support_queue.SUPPORT_NOTIFICATIONS_PATTERN == queue.SUPPORT_NOTIFICATIONS_PATTERN
    assert support_queue.EVENT_ORDER_STATUS_CHANGED == queue.EVENT_ORDER_STATUS_CHANGED
    assert support_queue.EVENT_ORDER_TRUCK_ASSIGNED == queue.EVENT_ORDER_TRUCK_ASSIGNED
    assert support_queue.EVENT_SUPPORT_TICKET_CREATED == queue.EVENT_SUPPORT_TICKET_CREATED
    assert support_queue.EVENT_SUPPORT_TICKET_REPLIED == queue.EVENT_SUPPORT_TICKET_REPLIED
    assert (
        support_queue.EVENT_SUPPORT_TICKET_STATUS_CHANGED
        == queue.EVENT_SUPPORT_TICKET_STATUS_CHANGED
    )


def test_notification_service_contract_matches_core():
    """Notification mikroservizi asosiy kodni import qilmaydi — nomlar qo'lda
    takrorlangan, shuning uchun bu yerda qulflanadi."""
    from notification_service import contracts as nc

    assert nc.EVENTS_EXCHANGE == queue.EVENTS_EXCHANGE
    assert nc.EVENT_ORDER_STATUS_CHANGED == queue.EVENT_ORDER_STATUS_CHANGED
    assert nc.EVENT_ORDER_WAYPOINT_CHANGED == queue.EVENT_ORDER_WAYPOINT_CHANGED
    assert nc.EVENT_ORDER_TRIP_STARTED == queue.EVENT_ORDER_TRIP_STARTED
    assert nc.EVENT_SUPPORT_TICKET_CREATED == queue.EVENT_SUPPORT_TICKET_CREATED
    assert nc.EVENT_SUPPORT_TICKET_REPLIED == queue.EVENT_SUPPORT_TICKET_REPLIED
    assert nc.EVENT_SUPPORT_TICKET_STATUS_CHANGED == queue.EVENT_SUPPORT_TICKET_STATUS_CHANGED
    assert nc.SUPPORT_NOTIFICATIONS_QUEUE == queue.SUPPORT_NOTIFICATIONS_QUEUE
    assert nc.SUPPORT_NOTIFICATIONS_PATTERN == queue.SUPPORT_NOTIFICATIONS_PATTERN
    assert nc.ORDER_NOTIFICATIONS_QUEUE == queue.ORDER_NOTIFICATIONS_QUEUE
    assert nc.ORDER_NOTIFICATIONS_PATTERN == queue.ORDER_NOTIFICATIONS_PATTERN


def test_notification_service_does_not_import_core():
    """Alohida image'ga faqat `notification_service/` ko'chiriladi."""
    import pathlib

    core = ("config.", "order", "driver", "users", "services", "Admin_panel", "manager", "handlers.", "workers")
    for path in pathlib.Path("notification_service").rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                module = stripped.split()[1]
                assert not module.startswith(core), f"{path}: {stripped}"


def test_tracking_service_does_not_import_core_and_matches_keys():
    import pathlib

    from tracking_service import store

    assert store.GLOBAL_CHANNEL == "driver_locations_channel"
    assert store.location_key(5) == "driver_location:5"
    assert store.gps_lost_key(5) == "driver_gps_lost:5"
    core = ("config.", "order", "driver", "users", "services", "Admin_panel", "manager", "handlers.", "workers")
    for path in pathlib.Path("tracking_service").rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not stripped.split()[1].startswith(core), f"{path}: {stripped}"
