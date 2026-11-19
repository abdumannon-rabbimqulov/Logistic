"""Redis'dagi jonli joylashuvlarni `drivers` jadvaliga davriy yozish.

GPS'ni endi `tracking_service` qabul qiladi va faqat Redis'ga yozadi (bazani bilmaydi).
Haydovchi ilovani yopgach ham dispatch uni "oxirgi ma'lum joylashuvi" bo'yicha topa
olishi uchun koordinata bazada ham bo'lishi kerak — buni shu modul `dispatch-worker`
sweep siklidan bajaradi (ilgari har GPS xabarida WS ichidan yozilardi).

Faqat bazadagidan YANGIROQ nuqta yoziladi (`last_location_at < ts`), shuning uchun
core'ning eski WS endpointi ham parallel ishlayversa, ma'lumot orqaga ketmaydi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import LIVE_LOC_DEFAULT_PERIOD_SEC
from driver.models import Driver
from services import live_location

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SEC = 60


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rows_to_sync(online: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Redis yozuvlaridan bazaga yoziladigan qatorlar (sof funksiya, testlanadi)."""
    rows = []
    for item in online:
        if item.get("stopped"):
            continue
        try:
            driver_id = int(item["driver_id"])
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        ts = _parse_ts(item.get("ts"))
        if ts is None:
            continue
        rows.append({"driver_id": driver_id, "lat": lat, "lon": lon, "ts": ts})
    return rows


async def sync_to_db(db: AsyncSession) -> int:
    """Qaytaradi: yangilangan haydovchilar soni."""
    rows = rows_to_sync(await live_location.get_all_online_drivers())
    if not rows:
        return 0
    updated = 0
    for row in rows:
        result = await db.execute(
            update(Driver)
            .where(
                Driver.id == row["driver_id"],
                or_(Driver.last_location_at.is_(None), Driver.last_location_at < row["ts"]),
            )
            .values(
                last_latitude=row["lat"],
                last_longitude=row["lon"],
                last_location_at=row["ts"],
                is_live_location_active=True,
                live_location_expires=row["ts"] + timedelta(seconds=LIVE_LOC_DEFAULT_PERIOD_SEC),
            )
        )
        updated += result.rowcount or 0
    await db.commit()
    return updated
