"""Jonli joylashuvni Redis'dan O'QISH (core uchun).

Yozish — `tracking_service` ning ishi (haydovchi GPS WebSocket'i). Core bu yerdan
oxirgi nuqtani, "GPS o'chdi" belgisini va admin xaritasi uchun oqimni o'qiydi,
hamda Redis'ga asoslangan qulf va bildirishnoma cheklovlaridan foydalanadi.
Kalitlar — `contracts/redis_keys.py`.
"""

import json
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional
import redis.asyncio as aioredis

from config.config import REDIS_HOST
from contracts import redis_keys

logger = logging.getLogger(__name__)

# Redis configuration
# We use the config value or fallback to defaults
REDIS_PORT = 6379

redis_client: Optional[aioredis.Redis] = None

def get_redis() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        url = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
        redis_client = aioredis.from_url(url, decode_responses=True)
    return redis_client

async def close_redis() -> None:
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None

async def claim_notice_slot(key: str, ttl_seconds: int) -> bool:
    """Takroriy bildirishnomalarni cheklash uchun: `True` — hozir yuborish mumkin.

    Redis'da `SET key 1 NX EX ttl` — kalit band bo'lsa `False` qaytadi, ya'ni shu
    haydovchiga yaqinda allaqachon xabar yuborilgan (spamning oldini oladi).
    Redis ishlamay qolsa `False` qaytadi — bildirishnoma yuborilmaydi, lekin
    dispatch oqimi buzilmaydi.
    """
    try:
        r = get_redis()
        return bool(await r.set(key, "1", nx=True, ex=ttl_seconds))
    except Exception:
        logger.exception("Bildirishnoma cheklovini tekshirib bo'lmadi: %s", key)
        return False


async def acquire_lock(key: str, ttl_seconds: int) -> bool:
    """Qisqa muddatli qulf: `True` — qulf shu chaqiruvda olindi.

    `claim_notice_slot` bilan bir xil `SET NX EX`, lekin XATO PAYTIDAGI xulqi teskari:
    Redis ishlamay qolsa `True` qaytadi ("fail-open"). Sabab — bu qulf faqat bir xil
    vazifa ikki marta yetkazilganda ortiqcha ish qilmaslik uchun optimallashtirish;
    to'g'rilikni baribir DB holati ta'minlaydi (`status`/`driver_id` tekshiruvi va
    `UPDATE ... WHERE status='pending'`). Redis o'chgani uchun qidiruvni butunlay
    to'xtatib qo'yish esa buyurtmalarni haydovchisiz qoldirardi.
    """
    try:
        r = get_redis()
        return bool(await r.set(key, "1", nx=True, ex=ttl_seconds))
    except Exception:
        logger.exception("Qulfni olishda xato (fail-open): %s", key)
        return True


async def release_lock(key: str) -> None:
    """Qulfni muddatidan oldin bo'shatadi (vazifa tugagach)."""
    try:
        await get_redis().delete(key)
    except Exception:
        logger.exception("Qulfni bo'shatishda xato: %s", key)


GPS_LOST_KEY = redis_keys.DRIVER_GPS_LOST_PREFIX + "{driver_id}"


async def get_gps_lost(driver_id: int) -> Optional[dict]:
    try:
        raw = await get_redis().get(GPS_LOST_KEY.format(driver_id=driver_id))
    except Exception:
        logger.exception("gps_lost belgisini o'qib bo'lmadi (driver %s)", driver_id)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def get_driver_location(driver_id: int) -> Optional[Dict[str, Any]]:
    """Alohida bitta haydovchining oxirgi lokatsiyasini olish."""
    try:
        r = get_redis()
        key = redis_keys.driver_location_key(driver_id)
        data = await r.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        logger.error(f"Error getting driver location for driver {driver_id}: {e}")
        return None

async def get_all_online_drivers() -> List[Dict[str, Any]]:
    """Barcha online (jonli translyatsiya qilayotgan) haydovchilarni olish.

    KEYS o'rniga SCAN ishlatiladi — KEYS butun Redis'ni bloklaydi va
    production'da kalitlar ko'payganda serverni sekinlashtiradi.
    """
    try:
        r = get_redis()
        keys: List[str] = []
        async for key in r.scan_iter(match=redis_keys.DRIVER_LOCATION_PATTERN, count=500):
            keys.append(key)
        if not keys:
            return []

        values = await r.mget(keys)
        drivers = []
        for val in values:
            if val:
                drivers.append(json.loads(val))
        return drivers
    except Exception as e:
        logger.error(f"Error getting all online drivers: {e}")
        return []

async def subscribe_location_updates() -> AsyncGenerator[Dict[str, Any], None]:
    """Redis orqali yangilangan lokatsiyalarni kanal orqali tinglash (Generator)."""
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(redis_keys.DRIVER_LOCATIONS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"])
                    yield payload
                except json.JSONDecodeError:
                    continue
    finally:
        await pubsub.unsubscribe(redis_keys.DRIVER_LOCATIONS_CHANNEL)
        await pubsub.close()
