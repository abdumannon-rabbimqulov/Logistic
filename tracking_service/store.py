"""Redis'dagi jonli joylashuvlar.

Kalit va kanal formati core'dagi `services/live_location.py` bilan BIR XIL —
core (dispatch, admin xaritasi, ETA, GPS kuzatuvchisi) shu ma'lumotni o'qiydi:
    driver_location:{id}        — oxirgi nuqta (JSON), TTL = LIVE_LOC_TTL_SEC
    driver_gps_lost:{id}        — ilova "GPS o'chdi" degan belgi
    driver_locations_channel    — barcha yangilanishlar (admin xaritasi)
    driver_location_ch:{id}     — faqat shu haydovchi (sender kuzatuvi) — YANGI:
        ilgari har sender WS butun oqimni olib, Python'da filtrlardi.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Optional

import redis.asyncio as aioredis
from redis.asyncio.client import PubSub

from contracts import redis_keys
from tracking_service.config import LIVE_LOC_TTL_SEC, REDIS_URL

logger = logging.getLogger(__name__)

GLOBAL_CHANNEL = redis_keys.DRIVER_LOCATIONS_CHANNEL
GPS_LOST_TTL_SEC = 6 * 3600

_redis: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def close() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# Kalitlar — `contracts/redis_keys.py` (core bilan yagona manba).
location_key = redis_keys.driver_location_key
driver_channel = redis_keys.driver_location_channel
gps_lost_key = redis_keys.driver_gps_lost_key
dispatch_channel = redis_keys.driver_dispatch_channel
order_updates_channel = redis_keys.order_updates_channel


def build_payload(identity: dict[str, Any], lat: float, lon: float, accuracy: Optional[float],
                  fix_time: Optional[datetime]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "driver_id": identity["driver_id"],
        "user_id": identity.get("user_id"),
        "full_name": identity.get("full_name"),
        "truck_number": identity.get("truck_number"),
        "truck_type_id": identity.get("truck_type_id"),
        "lat": lat,
        "lon": lon,
        "accuracy": accuracy,
        "ts": (fix_time or now).isoformat(),
        "expires_at": (now + timedelta(seconds=LIVE_LOC_TTL_SEC)).isoformat(),
    }


async def save_location(payload: dict[str, Any]) -> None:
    r = get_redis()
    driver_id = int(payload["driver_id"])
    data = json.dumps(payload)
    async with r.pipeline(transaction=False) as pipe:
        pipe.set(location_key(driver_id), data, ex=LIVE_LOC_TTL_SEC)
        pipe.delete(gps_lost_key(driver_id))
        pipe.publish(GLOBAL_CHANNEL, data)
        pipe.publish(driver_channel(driver_id), data)
        await pipe.execute()


async def mark_gps_lost(driver_id: int, reason: str) -> None:
    payload = json.dumps({"reason": reason, "at": datetime.now(timezone.utc).isoformat()})
    # NX: birinchi yo'qolish vaqti saqlanadi.
    await get_redis().set(gps_lost_key(driver_id), payload, ex=GPS_LOST_TTL_SEC, nx=True)


async def stop(driver_id: int) -> None:
    r = get_redis()
    now = datetime.now(timezone.utc).isoformat()
    data = json.dumps({"driver_id": driver_id, "lat": 0.0, "lon": 0.0, "ts": now, "expires_at": now, "stopped": True})
    await r.delete(location_key(driver_id))
    await r.publish(GLOBAL_CHANNEL, data)
    await r.publish(driver_channel(driver_id), data)


async def get_location(driver_id: int) -> Optional[dict[str, Any]]:
    raw = await get_redis().get(location_key(driver_id))
    return json.loads(raw) if raw else None


async def open_subscription(channel: str) -> PubSub:
    """Kanalga obuna — qaytgan paytda obuna ALLAQACHON faol (keyingi xabar yo'qolmaydi)."""
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(channel)
    return pubsub


async def iter_json(pubsub: PubSub, channel: str) -> AsyncGenerator[dict[str, Any], None]:
    """Obunadagi JSON xabarlar; generator yopilganda obuna ham yopiladi."""
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                yield json.loads(message["data"])
            except (TypeError, ValueError):
                continue
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


async def subscribe_driver(driver_id: int) -> AsyncGenerator[dict[str, Any], None]:
    channel = driver_channel(driver_id)
    async for payload in iter_json(await open_subscription(channel), channel):
        yield payload
