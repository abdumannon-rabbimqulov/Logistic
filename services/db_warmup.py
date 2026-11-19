"""DB ulanish pool'ini oldindan "isitish" — ilova ishga tushganda.

Nega kerak (yuklama testi, 2026-11-19): asyncpg har YANGI ulanishda so'rov natijasidagi
maxsus turlarni (enum'lar, PostGIS geometry) `WITH RECURSIVE typeinfo_tree ...`
so'rovi bilan o'rganadi. Bu bir ulanish uchun arzon (~40 ms), lekin deploy'dan keyin
pool bo'sh turganda yuklama kelsa, o'nlab ulanish bir vaqtda ochilib, DB CPU'sini
to'ldiradi. Testda restart'dan keyin 450 foydalanuvchida javoblar 2 daqiqa davomida
1–6 s bo'lib qoldi, issiq pool bilan esa xuddi shu yuklamada p95 61 ms edi.

Shuning uchun ishga tushganda pool'dagi barcha ulanishlar ochiladi va har birida
barcha jadvallar bo'yicha `SELECT * ... LIMIT 0` bajariladi: natija tavsifi orqali
asyncpg kerakli turlarni oldindan o'rganib qo'yadi. Xato bo'lsa ilova baribir ishga
tushadi — isitish faqat optimallashtirish.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def warm_pool(engine: AsyncEngine, size: int, tables: list[str]) -> None:
    probes = [text(f'SELECT * FROM "{name}" LIMIT 0') for name in tables]

    async def _one() -> None:
        async with engine.connect() as conn:
            for probe in probes:
                await conn.execute(probe)

    try:
        # Ulanishlar bir vaqtda ushlab turiladi — aks holda pool bitta ulanishni
        # qayta-qayta berib, qolganlari ochilmay qolardi.
        await asyncio.gather(*(_one() for _ in range(size)))
        logger.info("DB pool isitildi: %s ulanish, %s jadval", size, len(tables))
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB pool'ni isitib bo'lmadi (ilova ishlayveradi): %s", exc)
