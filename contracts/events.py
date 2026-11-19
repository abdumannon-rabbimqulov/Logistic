"""RabbitMQ topologiyasi va biznes hodisalari nomlari.

Routing key'lar SHARTNOMA: o'zgartirilsa barcha iste'molchilar buziladi —
`tests/test_event_contract.py` ularni qotirib qo'ygan.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

EVENTS_EXCHANGE = "logistika.events"

# ── Buyurtma hodisalari (core chiqaradi, transactional outbox orqali) ────────
EVENT_ORDER_STATUS_CHANGED = "order.status_changed"
EVENT_ORDER_TRUCK_ASSIGNED = "order.truck_assigned"
# Nuqta (yuk olish/tushirish) holati o'zgardi: ARRIVED / COMPLETED / SKIPPED.
EVENT_ORDER_WAYPOINT_CHANGED = "order.waypoint_changed"
# Haydovchi "Start" ni bosdi — yuk olish nuqtasiga yo'lga chiqdi.
EVENT_ORDER_TRIP_STARTED = "order.trip_started"
# Tayyor matnli bildirishnoma: core matn va qabul qiluvchilarni hal qiladi,
# notification_service yuboradi.
EVENT_ORDER_NOTICE = "order.notice"

# ── Chat hodisalari (chat_service chiqaradi) ──────────────────────────────────
EVENT_CHAT_MESSAGE_CREATED = "chat.message_created"

# ── Support hodisalari (support_service chiqaradi) ───────────────────────────
EVENT_SUPPORT_TICKET_CREATED = "support.ticket_created"
EVENT_SUPPORT_TICKET_REPLIED = "support.ticket_replied"
EVENT_SUPPORT_TICKET_STATUS_CHANGED = "support.ticket_status_changed"

ALL_EVENTS = frozenset({
    EVENT_ORDER_STATUS_CHANGED,
    EVENT_ORDER_TRUCK_ASSIGNED,
    EVENT_ORDER_WAYPOINT_CHANGED,
    EVENT_ORDER_TRIP_STARTED,
    EVENT_ORDER_NOTICE,
    EVENT_SUPPORT_TICKET_CREATED,
    EVENT_SUPPORT_TICKET_REPLIED,
    EVENT_SUPPORT_TICKET_STATUS_CHANGED,
    EVENT_CHAT_MESSAGE_CREATED,
})

# ── Navbatlar (topic exchange'ga bog'lanish) ─────────────────────────────────
# Support buyurtma hodisalarini tinglaydi (murojaatga tizim izohi qo'shish uchun).
SUPPORT_EVENTS_QUEUE = "support.order_events"
SUPPORT_EVENTS_PATTERN = "order.*"
# Notification: support hodisalari bo'yicha Telegram xabarlari.
SUPPORT_NOTIFICATIONS_QUEUE = "support.notifications"
SUPPORT_NOTIFICATIONS_PATTERN = "support.*"
# Notification: buyurtma hodisalari bo'yicha Telegram xabarlari.
ORDER_NOTIFICATIONS_QUEUE = "notifications.order_events"
ORDER_NOTIFICATIONS_PATTERN = "order.*"
# Chat: buyurtma hodisalaridan ishtirokchilarni oladi.
CHAT_ORDER_EVENTS_QUEUE = "chat.order_events"
CHAT_ORDER_EVENTS_PATTERN = "order.*"
# Notification: chatdagi yangi xabar bo'yicha Telegram xabari.
CHAT_NOTIFICATIONS_QUEUE = "chat.notifications"
CHAT_NOTIFICATIONS_PATTERN = "chat.*"


def build_envelope(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Hodisa konverti — barcha servislarda bir xil ko'rinish.

    `event_id` iste'molchiga takroriy yetkazishni (at-least-once) aniqlash imkonini
    beradi, `occurred_at` esa xabar navbatda kutib qolganda ham haqiqiy vaqtni saqlaydi.
    """
    return {
        "event": event,
        "event_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }
