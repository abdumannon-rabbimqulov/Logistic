"""Qidiruv (dispatch) qachon boshlanishi — sof funksiyalar, bazaga murojaatsiz.

Alohida modul: `order/schemas.py` javobda `dispatch_starts_at` ni ko'rsatadi.
Ilgari buning uchun `services.dispatch` ni import qilardi, u esa `order.crud` ni —
natijada aylanma import funksiya ichidagi kech import bilan yashirilgan edi.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from config.config import DISPATCH_LEAD_HOURS

# Rejalashtirilgan buyurtma uchun qidiruv yuklashdan shuncha oldin boshlanadi.
# DIQQAT: bu `services.dispatch.SCHEDULED_LEAD_SEC` EMAS — u haydovchi allaqachon
# topilgandan keyin SCHEDULED→ACCEPTED o'tishi uchun (30 daqiqa). Bu esa qidiruvning
# O'ZI qachon boshlanishini belgilaydi.
DISPATCH_START_LEAD_SEC = DISPATCH_LEAD_HOURS * 3600


def dispatch_starts_at(order) -> datetime:
    """Shu buyurtma uchun qidiruv boshlanishi kerak bo'lgan payt.

    Yuklash vaqtidan `DISPATCH_START_LEAD_SEC` ayriladi. Yuklash yaqin bo'lsa
    (yoki allaqachon o'tgan bo'lsa) natija o'tmishda bo'ladi — ya'ni "hoziroq".
    """
    pickup_at = order.pickup_at
    if pickup_at.tzinfo is None:
        pickup_at = pickup_at.replace(tzinfo=timezone.utc)
    return pickup_at - timedelta(seconds=DISPATCH_START_LEAD_SEC)


def is_dispatch_due(order, *, now: Optional[datetime] = None) -> bool:
    """Qidiruvni boshlash vaqti keldimi."""
    return dispatch_starts_at(order) <= (now or datetime.now(timezone.utc))
