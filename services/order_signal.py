"""Buyurtma sahifasiga "buyurtma o'zgardi" signali (Redis pub/sub → tracking_service WS).

Ilgari sender buyurtma sahifasi har 5–10 soniyada `GET /orders/{id}` so'rardi. Endi
sahifa `/orders/{id}/ws/updates` WebSocket'ini ochib turadi va faqat signal kelganda
so'raydi (zaxira so'rov — 30–60 s da). Signal manbalari:
  * outbox relay — buyurtma bilan bog'liq har hodisa (status, nuqta, xabar) commit'dan
    keyin shu yerdan o'tadi (`services/outbox.py`);
  * dispatch — qidiruv raundi, narx oshirish so'rovi, to'xtatish/davom ettirish
    (bular outbox hodisasi emas, lekin sahifada ko'rinadi).
"""

from __future__ import annotations

from typing import Iterable, Optional

from contracts import redis_keys
from services import realtime_signal


async def notify_orders(order_ids: Iterable[Optional[int]]) -> None:
    await realtime_signal.publish(
        (redis_keys.order_updates_channel(int(i)) for i in order_ids if i is not None),
        redis_keys.ORDER_CHANGED_EVENT,
    )
