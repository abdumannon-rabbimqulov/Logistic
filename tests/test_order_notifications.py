"""Senderga boradigan buyurtma xabarlari: qaysi hodisada xabar bor, qaysida yo'q."""

import pytest

from notification_service.handlers import orders as order_handlers
from notification_service.handlers.orders import sender_message_for
from services import queue

S = queue.EVENT_ORDER_STATUS_CHANGED
W = queue.EVENT_ORDER_WAYPOINT_CHANGED


@pytest.mark.parametrize(
    "event, data, expected",
    [
        (S, {"old_status": "ACCEPTED", "new_status": "IN_PROGRESS"}, "yo'lga chiqdi"),
        (S, {"old_status": "IN_PROGRESS", "new_status": "COMPLETED"}, "yetkazildi"),
        (S, {"old_status": "ACCEPTED", "new_status": "CANCELLED", "changed_by_user_id": 1}, "bekor qilindi"),
        (S, {"old_status": "ACCEPTED", "new_status": "PENDING"}, "qayta qidirilmoqda"),
        (W, {"new_status": "ARRIVED", "waypoint_type": "PICKUP"}, "yuk olish joyiga"),
        (W, {"new_status": "ARRIVED", "waypoint_type": "DELIVERY"}, "yetkazish manziliga"),
    ],
)
def test_messages_sent(event, data, expected):
    text = sender_message_for(event, {"order_id": 7, "customer_id": 50, **data})
    assert text is not None and expected in text and "#7" in text


@pytest.mark.parametrize(
    "event, data",
    [
        # "Haydovchi topildi" ni dispatch o'zi yuboradi — takrorlanmasin.
        (S, {"old_status": "PENDING", "new_status": "ACCEPTED"}),
        (S, {"old_status": "SCHEDULED", "new_status": "ACCEPTED"}),
        # Sender o'zi bekor qilgan.
        (S, {"old_status": "PENDING", "new_status": "CANCELLED", "changed_by_user_id": 50}),
        (W, {"new_status": "COMPLETED", "waypoint_type": "PICKUP"}),
        ("support.ticket_created", {}),
    ],
)
def test_no_message(event, data):
    assert sender_message_for(event, {"order_id": 7, "customer_id": 50, **data}) is None


def test_handle_builds_message_for_customer():
    [msg] = order_handlers.handle(S, {"order_id": 7, "customer_id": 50, "new_status": "COMPLETED"})
    assert msg.chat_id == 50 and "yetkazildi" in msg.text
