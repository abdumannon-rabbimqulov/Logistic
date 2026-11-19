"""Yordam xizmati hodisalari: murojaat egasiga va xodimlarga Telegram xabarlari.

Har bir hodisa ikki tomonga borishi mumkin: xodimlarga (nazorat uchun) va murojaat
egasiga (u javobni kutayotgan odam). Ikkalasi mustaqil.

Xodimlar = `ADMIN` + `STAFF_NOTIFY_IDS` (menejerlar). Murojaat biror xodimga
biriktirilgan bo'lsa (`assigned_to`, support_service o'ziga olish yoki birinchi
javobda belgilaydi), foydalanuvchining yangi xabari FAQAT o'shanga boradi —
boshqa xodimlar ishlanayotgan murojaat haqida shovqin olmasin.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from notification_service import config
from contracts import events as c
from notification_service.messages import Outgoing

STAFF_ROLES = {"admin", "manager"}


# support_service/models.py `TicketStatus` qiymatlari.
_TICKET_STATUS_LABEL = {
    "open": "ochiq",
    "in_progress": "ko'rib chiqilmoqda",
    "resolved": "hal qilindi",
    "closed": "yopildi",
}


def staff_ids() -> frozenset[int]:
    return config.ADMIN_IDS | config.STAFF_NOTIFY_IDS


def _staff_notice(title: str, body: str) -> list[Outgoing]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = f"💬 {title}\n{now}\n\n{body}"
    return [Outgoing(chat_id, text) for chat_id in sorted(staff_ids())]


def _who(name: Any, user_id: Any, role: Any) -> str:
    label = str(name).strip() if name else f"id={user_id}"
    return f"{label} ({role or '-'})"


def format_ticket_created(data: dict[str, Any]) -> tuple[str, str]:
    """Foydalanuvchi yordam chatiga birinchi marta yozdi (har foydalanuvchiga bitta chat)."""
    order_part = f"Buyurtma: #{data['order_id']}\n" if data.get("order_id") else ""
    body = (
        f"Chat: #{data.get('ticket_id')}\n"
        f"Foydalanuvchi: {_who(data.get('user_name'), data.get('user_id'), data.get('user_role'))}\n"
        f"{order_part}\n"
        f"{(data.get('body') or '')[:500]}"
    )
    return "Yangi yordam chati", body


def _message_text(data: dict[str, Any], limit: int) -> str:
    text = (data.get("message") or "").strip()[:limit]
    count = data.get("attachments")
    if count:
        text = (text + "\n" if text else "") + f"📎 Biriktirma: {count} ta"
    return text


def format_ticket_replied(data: dict[str, Any]) -> tuple[str, str]:
    order_part = f"Buyurtma: #{data['order_id']}\n" if data.get("order_id") else ""
    body = (
        f"Chat: #{data.get('ticket_id')}\n"
        f"Muallif: {_who(data.get('author_name'), data.get('author_user_id'), data.get('author_role'))}\n"
        f"{order_part}\n"
        f"{_message_text(data, 500)}"
    )
    title = "Hal qilingan chat qayta ochildi" if data.get("reopened") else "Yordam chatida yangi xabar"
    return title, body


def user_text_ticket_created(data: dict[str, Any]) -> str:
    return (
        "✅ Xabaringiz yordam xizmatiga yetib bordi.\n\n"
        "Operatorlarimiz tez orada javob beradi. Javob shu yerga va ilovadagi "
        "\"Yordam\" chatiga keladi."
    )


def user_text_ticket_replied(data: dict[str, Any]) -> str:
    return (
        "💬 Yordam xizmatidan javob\n\n"
        f"{_message_text(data, 1500)}\n\n"
        "Javob yozish uchun ilovadagi \"Yordam\" chatini oching."
    )


def user_text_status_changed(data: dict[str, Any]) -> str:
    new_status = str(data.get("new_status", ""))
    if new_status in {"resolved", "closed"}:
        return "✅ Savolingiz hal qilindi deb belgilandi.\n\nYana savol bo'lsa, shu chatga yozavering."
    label = _TICKET_STATUS_LABEL.get(new_status, new_status)
    return f"ℹ️ Yordam xizmati: savolingiz holati — {label}."


def _to_user(chat_id: Any, text: str) -> list[Outgoing]:
    try:
        return [Outgoing(int(chat_id), text)] if chat_id else []
    except (TypeError, ValueError):
        return []


def _staff_reply_to_owner(data: dict[str, Any]) -> bool:
    """Xodim BOSHQA odamning murojaatiga javob yozdi (o'z murojaatida emas)."""
    return str(data.get("author_role")) in STAFF_ROLES and data.get("author_user_id") != data.get(
        "ticket_user_id"
    )


def handle(event: str, data: dict[str, Any]) -> list[Outgoing]:
    if event == c.EVENT_SUPPORT_TICKET_CREATED:
        return _to_user(data.get("user_id"), user_text_ticket_created(data)) + _staff_notice(
            *format_ticket_created(data)
        )
    if event == c.EVENT_SUPPORT_TICKET_REPLIED:
        if _staff_reply_to_owner(data):
            # Xodimning javobi — murojaat egasi aynan shuni kutib turibdi.
            return _to_user(data.get("ticket_user_id"), user_text_ticket_replied(data))
        title, body = format_ticket_replied(data)
        assignee = data.get("assigned_to")
        if assignee and assignee != data.get("author_user_id"):
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return _to_user(assignee, f"💬 {title}\n{now}\n\n{body}")
        return _staff_notice(title, body)
    if event == c.EVENT_SUPPORT_TICKET_STATUS_CHANGED:
        # Egasining o'zi yopgan bo'lsa unga "holat o'zgardi" deyish ortiqcha.
        if data.get("changed_by_user_id") is not None and data.get("changed_by_user_id") == data.get(
            "ticket_user_id"
        ):
            return []
        # "Ochiq" ga qaytarish — xodimlarning ichki ishi, foydalanuvchiga shovqin.
        if data.get("new_status") == "open":
            return []
        return _to_user(data.get("ticket_user_id"), user_text_status_changed(data))
    return []
