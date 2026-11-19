"""Buyurtma bo'yicha tayyor matnli bildirishnomalar — outbox orqali notification_service'ga.

Core bu yerda faqat NIMA va KIMGA yuborishni hal qiladi (masalan menejerlar ro'yxati
bazada). Telegram'ga yuborish — `notification_service` ning ishi (`order.notice`
hodisasi). Ilgari GPS va "Start" eslatmalari core ichidan Telegram'ga to'g'ridan-
to'g'ri yuborilardi; endi ular ham biznes o'zgarishi bilan bitta tranzaksiyada
saqlanadi va broker o'chiq bo'lsa yo'qolmaydi.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from services import outbox, queue


def staff_text(title: str, details: str) -> str:
    """Xodimlarga boradigan xabar ko'rinishi (`utils/admin_alerts.send_notice_to_admins` bilan bir xil)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"💬 {title}\n{now}\n\n{details}"


def enqueue_notice(
    db: AsyncSession, *, order_id: int, recipient_ids: Iterable[int], text: str, kind: str
) -> None:
    """Hodisani joriy tranzaksiyaga qo'shadi — commit'ni CHAQIRUVCHI qiladi."""
    recipients = sorted({int(r) for r in recipient_ids if r})
    if not recipients or not text:
        return
    outbox.enqueue(
        db,
        queue.EVENT_ORDER_NOTICE,
        {"order_id": order_id, "recipient_ids": recipients, "text": text, "kind": kind},
    )
