"""Chat qoidalari (sof funksiyalar): ishtirokchi, readonly, buyurtma hodisalari."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from chat_service import domain
from chat_service.models import Conversation, Message

from .conftest import DRIVER_ID, DRIVER_USER, SENDER, STRANGER

DAY = 24 * 3600
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def ev(status=None, *, event=domain.EVENT_ORDER_STATUS_CHANGED, at=T0, driver_id=DRIVER_ID, **extra):
    data = {"order_id": 5, "customer_id": SENDER, "driver_id": driver_id, "new_status": status, **extra}
    parsed = domain.parse_order_event(event, data, at)
    assert parsed is not None
    return parsed


def open_conv(**kw) -> Conversation:
    conv = domain.apply_order_event(None, ev("ACCEPTED", driver_user_id=DRIVER_USER), readonly_after_s=DAY)
    assert conv is not None
    for k, v in kw.items():
        setattr(conv, k, v)
    return conv


# --- ishtirokchi ---------------------------------------------------------------


def test_only_participants_have_role():
    conv = open_conv()
    assert domain.role_of(conv, SENDER) == domain.ROLE_SENDER
    assert domain.role_of(conv, DRIVER_USER) == domain.ROLE_DRIVER
    assert domain.role_of(conv, STRANGER) is None
    assert domain.peer_user_id(conv, SENDER) == DRIVER_USER
    assert domain.peer_user_id(conv, DRIVER_USER) == SENDER
    assert domain.peer_user_id(conv, STRANGER) is None


def test_unknown_driver_user_is_not_participant():
    conv = open_conv(driver_user_id=None)
    assert not domain.is_participant(conv, DRIVER_USER)


# --- readonly ------------------------------------------------------------------


def test_chat_becomes_readonly_24h_after_completion():
    conv = open_conv()
    domain.apply_order_event(conv, ev("COMPLETED", at=T0 + timedelta(hours=2)), readonly_after_s=DAY)
    assert conv.readonly_at == T0 + timedelta(hours=26)

    just_before = T0 + timedelta(hours=25, minutes=59)
    assert domain.effective_status(conv, just_before) == domain.STATUS_OPEN
    assert domain.write_block_reason(conv, just_before) is None

    after = T0 + timedelta(hours=26)
    assert domain.effective_status(conv, after) == domain.STATUS_READONLY
    assert domain.write_block_reason(conv, after)


def test_cancelled_also_closes_after_24h():
    conv = open_conv()
    domain.apply_order_event(conv, ev("CANCELLED", at=T0 + timedelta(hours=1)), readonly_after_s=DAY)
    assert domain.effective_status(conv, T0 + timedelta(hours=26)) == domain.STATUS_READONLY


def test_naive_datetime_from_sqlite_is_treated_as_utc():
    conv = open_conv(readonly_at=datetime(2026, 11, 2, 12, 0))  # tz yo'q
    assert domain.effective_status(conv, datetime(2026, 11, 2, 12, 1, tzinfo=timezone.utc)) == "readonly"


# --- hodisalar -----------------------------------------------------------------


def test_accepted_opens_conversation():
    conv = open_conv()
    assert conv.order_id == 5
    assert conv.sender_user_id == SENDER
    assert conv.driver_id == DRIVER_ID
    assert conv.driver_user_id == DRIVER_USER
    assert conv.status == domain.STATUS_OPEN
    assert conv.order_status == "ACCEPTED"


def test_pending_or_scheduled_does_not_create_chat():
    for status in ("PENDING", "SCHEDULED", "COMPLETED", "CANCELLED"):
        assert domain.apply_order_event(None, ev(status), readonly_after_s=DAY) is None


def test_truck_assigned_opens_chat():
    conv = domain.apply_order_event(
        None, ev(None, event=domain.EVENT_ORDER_TRUCK_ASSIGNED), readonly_after_s=DAY
    )
    assert conv is not None and conv.driver_id == DRIVER_ID and conv.driver_user_id is None


def test_lowercase_status_is_normalised():
    conv = domain.apply_order_event(None, ev("accepted"), readonly_after_s=DAY)
    assert conv is not None and conv.order_status == "ACCEPTED"


def test_stale_event_does_not_reopen_closed_chat():
    conv = open_conv()
    domain.apply_order_event(conv, ev("COMPLETED", at=T0 + timedelta(hours=3)), readonly_after_s=DAY)
    stale = ev("IN_PROGRESS", at=T0 + timedelta(hours=1))
    assert domain.apply_order_event(conv, stale, readonly_after_s=DAY) is None
    assert conv.readonly_at is not None


def test_driver_replaced_resets_driver_user():
    conv = open_conv()
    domain.apply_order_event(
        conv, ev("ACCEPTED", at=T0 + timedelta(minutes=5), driver_id=DRIVER_ID + 1), readonly_after_s=DAY
    )
    assert conv.driver_id == DRIVER_ID + 1
    assert conv.driver_user_id is None  # eski haydovchi endi kira olmaydi
    assert not domain.is_participant(conv, DRIVER_USER)


def test_back_to_pending_removes_driver_and_blocks_writing():
    conv = open_conv()
    domain.apply_order_event(
        conv, ev("PENDING", at=T0 + timedelta(minutes=5), driver_id=None), readonly_after_s=DAY
    )
    assert conv.driver_id is None and conv.driver_user_id is None
    assert domain.write_block_reason(conv, T0 + timedelta(minutes=6))


def test_reaccept_after_completion_reopens():
    conv = open_conv()
    domain.apply_order_event(conv, ev("COMPLETED", at=T0 + timedelta(hours=1)), readonly_after_s=DAY)
    domain.apply_order_event(conv, ev("IN_PROGRESS", at=T0 + timedelta(hours=2)), readonly_after_s=DAY)
    assert conv.readonly_at is None


def test_garbage_events_ignored():
    assert domain.parse_order_event("order.deleted", {"order_id": 1}) is None
    assert domain.parse_order_event(domain.EVENT_ORDER_STATUS_CHANGED, {"order_id": "x"}) is None


# --- tahrir / o'chirish ------------------------------------------------------------


def _msg(**kw) -> Message:
    base = dict(sender_user_id=SENDER, kind="text", text="salom", created_at=T0)
    base.update(kw)
    return Message(**base)


def test_edit_rules():
    now = T0 + timedelta(hours=1)
    assert domain.can_edit(_msg(), SENDER, now, 48 * 3600) is None
    assert domain.can_edit(_msg(), DRIVER_USER, now, 48 * 3600)
    assert domain.can_edit(_msg(kind="voice"), SENDER, now, 48 * 3600)
    assert domain.can_edit(_msg(kind="location"), SENDER, now, 48 * 3600)
    assert domain.can_edit(_msg(kind="photo"), SENDER, now, 48 * 3600) is None  # izoh
    assert domain.can_edit(_msg(deleted_at=now), SENDER, now, 48 * 3600)
    assert domain.can_edit(_msg(), SENDER, T0 + timedelta(hours=49), 48 * 3600)


def test_delete_rules():
    assert domain.can_delete(_msg(), SENDER) is None
    assert domain.can_delete(_msg(), DRIVER_USER)
    assert domain.can_delete(_msg(deleted_at=T0), SENDER)


def test_preview_text():
    assert domain.preview_text("text", "  salom ") == "salom"
    assert domain.preview_text("voice", None) == "🎤 Ovozli xabar"
    assert domain.preview_text("photo", "yuk") == "📷 Rasm: yuk"
