"""GPS nuqtasi vaqtini tekshirish (core'dagi `driver/router.py` bilan bir xil qoida)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from tracking_service.config import LIVE_LOC_TTL_SEC


def parse_fix_time(raw, now: datetime) -> Optional[datetime]:
    """Epoch millisekund → UTC datetime. `None` — vaqt yuborilmagan (eski klient).
    Kelajakdagi vaqt `now` ga tenglanadi (qurilma soati noto'g'ri bo'lishi mumkin)."""
    if raw is None:
        return None
    try:
        fix = datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return now if fix > now else fix


def is_stale_fix(fix: Optional[datetime], now: datetime) -> bool:
    return fix is not None and (now - fix).total_seconds() > LIVE_LOC_TTL_SEC
