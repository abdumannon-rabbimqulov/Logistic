"""Redis pub/sub orqali WebSocket signallari — umumiy yordamchi.

`dispatch_signal` (haydovchi takliflari) va `order_signal` (buyurtma sahifasi) shu yerdan
foydalanadi. Signal DB `commit` dan KEYIN yuboriladi (ilova yangi holatni o'qiy olsin).
Redis ishlamasa jim o'tadi: signal ixtiyoriy tezlatgich, ilovada zaxira so'rov bor.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable

logger = logging.getLogger(__name__)


async def publish(channels: Iterable[str], event: str) -> None:
    names = sorted(set(channels))
    if not names:
        return
    from services.live_location import get_redis

    payload = json.dumps({"event": event})
    try:
        redis = get_redis()
        for channel in names:
            await redis.publish(channel, payload)
    except Exception as exc:  # noqa: BLE001 — signal ixtiyoriy, asosiy oqim to'xtamasin
        logger.warning("Signal yuborilmadi (%s): %s", names, exc)
