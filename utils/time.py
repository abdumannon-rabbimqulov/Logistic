"""Vaqt bilan ishlash uchun umumiy yordamchilar."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def parse_iso_utc(value: Any) -> Optional[datetime]:
    """ISO 8601 qatorni UTC `datetime` ga aylantiradi; bo'sh/yaroqsiz bo'lsa `None`.

    Vaqt mintaqasi ko'rsatilmagan qiymat UTC deb olinadi (Redis'dagi `ts` va boshqa
    ichki qiymatlar shunday yoziladi).
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_seconds(moment: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    """`moment` dan beri o'tgan soniyalar (`None` — vaqt noma'lum)."""
    if moment is None:
        return None
    return ((now or datetime.now(timezone.utc)) - moment).total_seconds()
