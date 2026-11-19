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

import json
import logging
from typing import Iterable, Optional

from contracts import redis_keys

logger = logging.getLogger(__name__)

_PAYLOAD = json.dumps({"event": redis_keys.DISPATCH_CHANGED_EVENT})


async def notify_drivers(driver_ids: Iterable[Optional[int]]) -> None:
    ids = {int(i) for i in driver_ids if i is not None}
    if not ids:
        return
    from services.live_location import get_redis

    try:
        redis = get_redis()
        for driver_id in ids:
            await redis.publish(redis_keys.driver_dispatch_channel(driver_id), _PAYLOAD)
    except Exception as exc:  # noqa: BLE001 — signal ixtiyoriy, asosiy oqim to'xtamasin
        logger.warning("Dispatch signali yuborilmadi (%s): %s", sorted(ids), exc)
