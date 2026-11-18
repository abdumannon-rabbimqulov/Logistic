"""Mavjud buyurtma nuqtalariga `region_id` yozadi (bir martalik, takror ishga tushirish xavfsiz).

`c3d9a1e5f720` migratsiyasidan keyin eski `order_waypoints` yozuvlarida `region_id` bo'sh —
jonli xaritadagi "qayerdan → qayerga" filteri ularni ko'rmaydi. Faqat `region_id IS NULL`
va koordinatasi bor nuqtalar yangilanadi.

    docker compose exec web python scripts/backfill_waypoint_regions.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, update  # noqa: E402

from config import registry  # noqa: E402,F401  — barcha modellar (mapper) ro'yxatdan o'tsin
from config.config import async_session  # noqa: E402
from order.models import OrderWaypoint  # noqa: E402
from services.regions import region_for_point  # noqa: E402

BATCH = 1000


async def main() -> None:
    updated = unresolved = 0
    async with async_session() as db:
        last_id = 0
        while True:
            rows = (
                await db.execute(
                    select(OrderWaypoint.id, OrderWaypoint.latitude, OrderWaypoint.longitude)
                    .where(
                        OrderWaypoint.id > last_id,
                        OrderWaypoint.region_id.is_(None),
                        OrderWaypoint.latitude.is_not(None),
                        OrderWaypoint.longitude.is_not(None),
                    )
                    .order_by(OrderWaypoint.id)
                    .limit(BATCH)
                )
            ).all()
            if not rows:
                break
            for wp_id, lat, lon in rows:
                region_id = region_for_point(lat, lon)
                if region_id is None:
                    unresolved += 1
                    continue
                await db.execute(
                    update(OrderWaypoint).where(OrderWaypoint.id == wp_id).values(region_id=region_id)
                )
                updated += 1
            await db.commit()
            last_id = rows[-1][0]
    print(f"region_id yozildi: {updated}, viloyati aniqlanmadi (O'zbekistondan tashqarida): {unresolved}")


if __name__ == "__main__":
    asyncio.run(main())
