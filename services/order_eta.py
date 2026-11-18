"""Sender kuzatish sahifasi uchun: haydovchi qayerda, joylashuvi yangimi va keyingi
nuqtagacha qancha qoldi (ETA).

Joylashuv "yangiligi" (freshness) shu yerda bitta ta'rif bilan hisoblanadi —
`services/location_watch.py` (ogohlantirishlar) ham shu funksiyalardan foydalanadi.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from config.config import LIVE_LOC_TTL_SEC
from services import live_location, osrm_client

logger = logging.getLogger(__name__)

ETA_CACHE_TTL_SEC = 60


@dataclass
class DriverFix:
    latitude: float
    longitude: float
    at: Optional[datetime]
    source: str  # "live" (Redis) | "last_known" (Driver jadvali)


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def latest_driver_fix(driver) -> Optional[DriverFix]:
    """Haydovchining eng so'nggi ma'lum nuqtasi: avval Redis, bo'lmasa DB."""
    live = await live_location.get_driver_location(driver.id)
    if live and live.get("lat") is not None and live.get("lon") is not None:
        return DriverFix(float(live["lat"]), float(live["lon"]), _parse_iso(live.get("ts")), "live")
    if driver.last_latitude is not None and driver.last_longitude is not None:
        at = driver.last_location_at
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return DriverFix(float(driver.last_latitude), float(driver.last_longitude), at, "last_known")
    return None


def fix_age_seconds(fix: Optional[DriverFix], now: Optional[datetime] = None) -> Optional[float]:
    if fix is None or fix.at is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - fix.at).total_seconds())


def is_fix_stale(fix: Optional[DriverFix], now: Optional[datetime] = None) -> bool:
    """Nuqta yo'q yoki `LIVE_LOC_TTL_SEC` (2 daqiqa) dan eski — joylashuv "jonli" emas."""
    age = fix_age_seconds(fix, now)
    return age is None or age > LIVE_LOC_TTL_SEC


def next_target_waypoint(order):
    """Haydovchi hozir boradigan nuqta: birinchi yopilmagan nuqta."""
    return order.current_waypoint


async def compute_eta(order, driver) -> dict[str, Any]:
    """Javob: joylashuv holati + (mumkin bo'lsa) keyingi nuqtagacha masofa/vaqt."""
    fix = await latest_driver_fix(driver)
    gps_lost = await live_location.get_gps_lost(driver.id)
    age = fix_age_seconds(fix)
    result: dict[str, Any] = {
        "location_updated_at": fix.at.isoformat() if fix and fix.at else None,
        "location_age_sec": int(age) if age is not None else None,
        "location_stale": is_fix_stale(fix),
        "gps_lost_reason": (gps_lost or {}).get("reason"),
        "target_type": None,
        "distance_km": None,
        "duration_min": None,
    }

    target = next_target_waypoint(order)
    if fix is None or target is None or target.latitude is None or target.longitude is None:
        return result
    result["target_type"] = target.type.value

    # Bir xil nuqta uchun OSRM'ga minutiga bir martadan ortiq bormaslik.
    cache_key = f"order_eta:{order.id}:{target.id}:{round(fix.latitude, 3)}:{round(fix.longitude, 3)}"
    redis = live_location.get_redis()
    try:
        cached = await redis.get(cache_key)
        if cached:
            result.update(json.loads(cached))
            return result
    except Exception:
        logger.debug("ETA keshini o'qib bo'lmadi", exc_info=True)

    try:
        route = await osrm_client.get_route(
            [(fix.latitude, fix.longitude), (float(target.latitude), float(target.longitude))]
        )
    except osrm_client.OSRMRouteError:
        logger.info("ETA: OSRM marshrut bermadi (order %s)", order.id)
        return result

    eta = {"distance_km": round(route.distance_km, 1), "duration_min": round(route.duration_min)}
    result.update(eta)
    try:
        await redis.set(cache_key, json.dumps(eta), ex=ETA_CACHE_TTL_SEC)
    except Exception:
        logger.debug("ETA keshini yozib bo'lmadi", exc_info=True)
    return result

