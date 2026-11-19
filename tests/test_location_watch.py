"""Haydovchi joylashuvi o'chganda kim va qachon ogohlantiriladi."""

from datetime import datetime, timedelta, timezone

import pytest

from tracking_service.fixes import is_stale_fix, parse_fix_time
from services.location_watch import Decision, decide


@pytest.mark.parametrize(
    "age, gps_lost, was_warned, expected",
    [
        (30, False, False, Decision()),  # hammasi joyida
        (30, False, True, Decision(recovered=True)),  # tiklandi
        (30, True, False, Decision(warn_driver=True)),  # ilova "GPS o'chdi" dedi
        (4 * 60, False, False, Decision(warn_driver=True)),  # 3+ daqiqa
        (11 * 60, False, False, Decision(warn_driver=True, warn_staff=True)),  # 10+ daqiqa
        (None, False, False, Decision(warn_driver=True, warn_staff=True)),  # nuqta umuman yo'q
    ],
)
def test_decide(age, gps_lost, was_warned, expected):
    assert decide(age, gps_lost, was_warned=was_warned) == expected


def test_parse_fix_time_and_staleness():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    ms = lambda dt: dt.timestamp() * 1000  # noqa: E731

    assert parse_fix_time(None, now) is None
    assert parse_fix_time("bad", now) is None
    # Kelajakdagi vaqt (noto'g'ri soat) hozirga tenglanadi.
    assert parse_fix_time(ms(now + timedelta(minutes=5)), now) == now

    fresh = parse_fix_time(ms(now - timedelta(seconds=30)), now)
    old = parse_fix_time(ms(now - timedelta(minutes=10)), now)
    assert not is_stale_fix(fresh, now)
    assert is_stale_fix(old, now)
    assert not is_stale_fix(None, now)  # eski klient: vaqt yuborilmagan
