"""Buyurtma hodisalari bo'yicha senderga Telegram xabarlari.

`workers/events_worker.py` `notifications.order_events` navbatidan (`order.*`)
hodisalarni oladi va shu modulga beradi. Kelajakdagi notification-service'ga
o'zgarishsiz ko'chadi: bu yerda bazaga murojaat yo'q, faqat hodisa ma'lumoti.

Qaysi o'tishlar XABAR BERMAYDI (takrorlanmasligi uchun):
  * PENDING → ACCEPTED/SCHEDULED — "haydovchi topildi" xabarini dispatch o'zi
    yuboradi (`services/dispatch.py: _notify_sender_driver_found`), u mashina
    raqamini ham biladi.
  * Sender o'zi bekor qilgani — u buni ilovada ko'rib turibdi.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config.config import WEBAPP_URL
from services import queue
from services.notifications import send_telegram_message

logger = logging.getLogger(__name__)


def sender_message_for(event: str, data: dict[str, Any]) -> Optional[str]:
    """Hodisa uchun senderga yuboriladigan matn yoki `None` (xabar kerak emas)."""
    order_id = data.get("order_id")
    if not order_id:
        return None

    if event == queue.EVENT_ORDER_STATUS_CHANGED:
        new_status = data.get("new_status")
        old_status = data.get("old_status")
        if new_status == "IN_PROGRESS" and old_status != "IN_PROGRESS":
            return f"🚚 #{order_id} buyurtmangiz yo'lga chiqdi — yuk ortildi."
        if new_status == "COMPLETED":
            return f"✅ #{order_id} buyurtmangiz yetkazildi. Xizmatimizdan foydalanganingiz uchun rahmat!"
        if new_status == "CANCELLED" and data.get("changed_by_user_id") != data.get("customer_id"):
            return f"❌ #{order_id} buyurtmangiz bekor qilindi. Savollar bo'lsa yordam xizmatiga yozing."
        if new_status == "PENDING" and old_status in {"ACCEPTED", "SCHEDULED"}:
            return f"🔎 #{order_id} buyurtmangiz uchun haydovchi qayta qidirilmoqda."
        return None

    if event == queue.EVENT_ORDER_WAYPOINT_CHANGED:
        if data.get("new_status") != "ARRIVED":
            return None
        if data.get("waypoint_type") == "PICKUP":
            return f"📍 Haydovchi #{order_id} buyurtma bo'yicha yuk olish joyiga yetib keldi."
        if data.get("waypoint_type") == "DELIVERY":
            return f"📍 Haydovchi #{order_id} buyurtma bo'yicha yetkazish manziliga yetib keldi."
        return None

    return None


def _track_button(order_id: int) -> Optional[dict]:
    """Mini-app'ni to'g'ridan-to'g'ri buyurtma sahifasida ochadigan tugma."""
    base = (WEBAPP_URL or "").rstrip("/")
    if not base.startswith("https://"):
        # Telegram web_app tugmasi faqat HTTPS'ni qabul qiladi (lokal dev'da tugmasiz).
        return None
    return {
        "inline_keyboard": [
            [{"text": "Buyurtmani ko'rish", "web_app": {"url": f"{base}/orders/{order_id}"}}]
        ]
    }


async def handle_order_event(event: str, data: dict[str, Any]) -> None:
    text = sender_message_for(event, data)
    customer_id = data.get("customer_id")
    if text is None or not customer_id:
        return
    # User.id — Telegram chat id (dispatch.py'dagi boshqa xabarlar ham shunday yuboriladi).
    await send_telegram_message(int(customer_id), text, reply_markup=_track_button(int(data["order_id"])))
