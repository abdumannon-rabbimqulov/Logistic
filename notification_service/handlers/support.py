"""Yordam xizmati hodisalari: murojaat egasiga va xodimlarga Telegram xabarlari.

Har bir hodisa ikki tomonga borishi mumkin: xodimlarga (nazorat uchun) va murojaat
egasiga (u javobni kutayotgan odam). Ikkalasi mustaqil.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from notification_service import config
from notification_service import contracts as c
from notification_service.messages import Outgoing

STAFF_ROLES = {"admin", "manager"}

_PRIORITY_LABEL = {"low": "past", "normal": "o'rta", "high": "yuqori", "urgent": "shoshilinch"}

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


def format_ticket_created(data: dict[str, Any]) -> tuple[str, str]:
    order_part = f"Buyurtma: #{data['order_id']}\n" if data.get("order_id") else ""
    priority = _PRIORITY_LABEL.get(str(data.get("priority", "")), data.get("priority", "-"))
    body = (
        f"Murojaat: #{data.get('ticket_id')}\n"
        f"Foydalanuvchi: {data.get('user_id')} ({data.get('user_role') or '-'})\n"
        f"{order_part}"
        f"Muhimlik: {priority}\n"
        f"Mavzu: {data.get('subject')}\n\n"
        f"{(data.get('body') or '')[:500]}"
    )
    return "Yangi yordam murojaati", body


def format_ticket_replied(data: dict[str, Any]) -> tuple[str, str]:
    body = (
        f"Murojaat: #{data.get('ticket_id')}\n"
        f"Muallif: {data.get('author_user_id')} ({data.get('author_role') or '-'})\n\n"
        f"{(data.get('message') or '')[:500]}"
    )
    return "Yordam murojaatiga yangi javob", body


def user_text_ticket_created(data: dict[str, Any]) -> str:
    return (
        f"✅ Murojaatingiz qabul qilindi — #{data.get('ticket_id')}\n"
        f"Mavzu: {data.get('subject')}\n\n"
        f"Operatorlarimiz tez orada javob beradi. Javob shu yerga va ilovadagi "
        f"\"Murojaatlar\" bo'limiga keladi."
    )


def user_text_ticket_replied(data: dict[str, Any]) -> str:
    return (
        f"💬 Murojaatingizga javob keldi — #{data.get('ticket_id')}\n\n"
        f"{(data.get('message') or '')[:1500]}\n\n"
        f"Javob yozish uchun ilovadagi \"Murojaatlar\" bo'limini oching."
    )


def user_text_status_changed(data: dict[str, Any]) -> str:
    new_status = str(data.get("new_status", ""))
    label = _TICKET_STATUS_LABEL.get(new_status, new_status)
    text = f"ℹ️ Murojaat #{data.get('ticket_id')} holati o'zgardi: {label}\nMavzu: {data.get('subject')}"
    if new_status in {"resolved", "closed"}:
        text += "\n\nSavolingiz qolgan bo'lsa, yangi murojaat oching."
    return text


def _to_user(chat_id: Any, text: str) -> list[Outgoing]:
    try:
        return [Outgoing(int(chat_id), text)] if chat_id else []
    except (TypeError, ValueError):
        return []


def handle(event: str, data: dict[str, Any]) -> list[Outgoing]:
    if event == c.EVENT_SUPPORT_TICKET_CREATED:
        return _to_user(data.get("user_id"), user_text_ticket_created(data)) + _staff_notice(
            *format_ticket_created(data)
        )
    if event == c.EVENT_SUPPORT_TICKET_REPLIED:
        if str(data.get("author_role")) in STAFF_ROLES:
            # Xodimning javobi — murojaat egasi aynan shuni kutib turibdi.
            return _to_user(data.get("ticket_user_id"), user_text_ticket_replied(data))
        return _staff_notice(*format_ticket_replied(data))
    if event == c.EVENT_SUPPORT_TICKET_STATUS_CHANGED:
        return _to_user(data.get("ticket_user_id"), user_text_status_changed(data))
    return []
