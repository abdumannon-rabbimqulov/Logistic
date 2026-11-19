"""Haydovchi ilovasiga "taklif o'zgardi" signali (Redis pub/sub → tracking_service WS).

Ilgari haydovchi ilovasi liniyada turganda har 3 soniyada `GET /orders/dispatch/active`
so'rardi — bu yuklama testida eng ko'p so'rov edi (har onlayn haydovchi = 0.33 so'rov/s).
Endi taklif yaratilganda yoki yopilganda (muddati o'tdi, bekor qilindi, qabul qilindi)
shu haydovchining kanaliga signal yuboriladi va ilova faqat shunda so'raydi.

Chaqirish qoidasi: signal DB `commit` dan KEYIN yuboriladi — aks holda ilova yangi
holatni o'qishga ulgurmay, eskisini olib qolishi mumkin. Redis ishlamasa jim o'tadi:
ilovada zaxira so'rov (uzoqroq oraliqda) bor.
"""

from __future__ import annotations

from typing import Iterable, Optional

from contracts import redis_keys
from services import realtime_signal


async def notify_drivers(driver_ids: Iterable[Optional[int]]) -> None:
    await realtime_signal.publish(
        (redis_keys.driver_dispatch_channel(int(i)) for i in driver_ids if i is not None),
        redis_keys.DISPATCH_CHANGED_EVENT,
    )
