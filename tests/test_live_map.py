"""Jonli yuk xaritasi: viloyat aniqlash va shaxsiy ma'lumot chiqib ketmasligi."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from order.models import OrderStatus, WaypointType
from order.schemas import LiveMapItem
from services import public_map, regions

FORBIDDEN_KEYS = {
    "full_name",
    "truck_number",
    "phone_number",
    "user_id",
    "driver_id",
    "order_id",
    "customer_id",
    "contact_name",
    "contact_phone",
    "id",
}


# ────────────────────────────────────────────────────────────
#  Viloyatlar
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "lat, lon, expected",
    [
        (41.3111, 69.2797, "Toshkent sh."),
        (41.4689, 69.5822, "Toshkent viloyati"),  # Chirchiq
        (40.7821, 72.3442, "Andijon viloyati"),
        (39.6542, 66.9597, "Samarqand viloyati"),
        (42.4531, 59.6103, "Qoraqalpog'iston Respublikasi"),  # Nukus
    ],
)
def test_region_for_point(lat, lon, expected):
    assert regions.region_name(regions.region_for_point(lat, lon)) == expected


def test_region_outside_uzbekistan_is_none():
    assert regions.region_for_point(43.2389, 76.8897) is None  # Olmaota
    assert regions.region_for_point(None, None) is None


def test_list_regions_has_all_14_tashkent_first():
    items = regions.list_regions()
    assert len(items) == 14
    assert items[0]["name"] == "Toshkent sh."


# ────────────────────────────────────────────────────────────
#  Shaxsiy ma'lumot
# ────────────────────────────────────────────────────────────

def test_live_map_item_schema_has_no_personal_fields():
    assert FORBIDDEN_KEYS.isdisjoint(LiveMapItem.model_fields)


def test_marker_id_is_stable_and_opaque():
    a = public_map.marker_id_for(42)
    assert a == public_map.marker_id_for(42)
    assert a != public_map.marker_id_for(43)
    assert len(a) == 16 and a.isalnum()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def unique(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return _Result(self.rows)


def _order():
    tt = SimpleNamespace(id=3, name="Isuzu 5 t", image_url=None, max_weight=Decimal("5"))
    driver = SimpleNamespace(
        id=7,
        last_latitude=None,
        last_longitude=None,
        last_location_at=None,
        truck_number="01A777AA",
        full_name="Ali Valiyev",
    )
    pickup = SimpleNamespace(
        type=WaypointType.PICKUP, address="Toshkent, Chilonzor", latitude=Decimal("41.28"),
        longitude=Decimal("69.20"), region_id=14, contact_name="X", contact_phone="+998901112233",
    )
    delivery = SimpleNamespace(
        type=WaypointType.DELIVERY, address="Andijon", latitude=Decimal("40.78"),
        longitude=Decimal("72.34"), region_id=1, contact_name="Y", contact_phone="+998901112244",
    )
    return SimpleNamespace(
        id=99, status=OrderStatus.IN_PROGRESS, driver=driver, truck_type=tt,
        waypoints=[pickup, delivery], weight=Decimal("4.5"), cargo_name="Mebel",
        billable_distance_km=330, total_distance_km=Decimal("331.2"),
        price=Decimal("3300000"), currency="UZS", customer_id=5,
    )


def test_in_transit_item_contains_cargo_but_no_personal_data():
    order = _order()
    live = {7: (40.9, 71.0)}
    items = asyncio.run(
        public_map._in_transit_items(_FakeDB([order]), live, from_region=None, to_region=None, truck_type_id=None)
    )
    assert len(items) == 1
    data = items[0].model_dump()

    assert data["has_cargo"] is True
    assert data["truck_type_name"] == "Isuzu 5 t"
    assert data["weight"] == Decimal("4.5")
    assert data["truck_max_weight"] == Decimal("5")
    assert data["load_percent"] == 90
    assert data["pickup_region"] == "Toshkent sh."
    assert data["delivery_region"] == "Andijon viloyati"
    assert data["price"] == Decimal("3300000")
    assert data["distance_km"] == Decimal("330")

    assert FORBIDDEN_KEYS.isdisjoint(data)
    blob = items[0].model_dump_json()
    for secret in ("01A777AA", "Ali Valiyev", "+99890111", '"99"'):
        assert secret not in blob


def test_in_transit_skips_driver_without_any_location():
    order = _order()
    items = asyncio.run(
        public_map._in_transit_items(_FakeDB([order]), {}, from_region=None, to_region=None, truck_type_id=None)
    )
    assert items == []


def test_in_transit_uses_fresh_last_known_location_only():
    order = _order()
    order.driver.last_latitude, order.driver.last_longitude = 41.0, 70.0
    order.driver.last_location_at = datetime.now(timezone.utc) - timedelta(hours=1)
    items = asyncio.run(
        public_map._in_transit_items(_FakeDB([order]), {}, from_region=None, to_region=None, truck_type_id=None)
    )
    assert len(items) == 1 and items[0].lat == 41.0

    order.driver.last_location_at = datetime.now(timezone.utc) - timedelta(days=2)
    items = asyncio.run(
        public_map._in_transit_items(_FakeDB([order]), {}, from_region=None, to_region=None, truck_type_id=None)
    )
    assert items == []


def test_empty_items_filter_by_current_region():
    tt = SimpleNamespace(id=3, name="Isuzu 5 t", image_url=None, max_weight=Decimal("5"))
    live = {1: (41.3111, 69.2797), 2: (40.7821, 72.3442)}  # Toshkent sh., Andijon
    db = _FakeDB([(1, tt), (2, tt)])

    all_items = asyncio.run(public_map._empty_items(db, live, from_region=None, truck_type_id=None))
    assert {i.current_region for i in all_items} == {"Toshkent sh.", "Andijon viloyati"}
    assert all(not i.has_cargo and i.price is None for i in all_items)

    andijon = asyncio.run(public_map._empty_items(db, live, from_region=1, truck_type_id=None))
    assert [i.current_region for i in andijon] == ["Andijon viloyati"]


def test_live_map_stats_cache_is_shared_by_mode_and_scoped_to_filters(monkeypatch):
    values = {}
    queries = []

    class Cache:
        async def get(self, key):
            return values.get(key)

        async def set(self, key, value, *, ex):
            values[key] = value
            assert ex == (30 if ":stats:" in key else 5)

    async def stats(_db, **filters):
        queries.append(filters)
        return public_map.LiveMapStats(period_days=30, count=len(queries))

    async def points():
        return {}

    async def items(*_args, **_kwargs):
        return []

    monkeypatch.setattr(public_map.live_location, "get_redis", Cache)
    monkeypatch.setattr(public_map, "_stats", stats)
    monkeypatch.setattr(public_map, "_live_points", points)
    monkeypatch.setattr(public_map, "_in_transit_items", items)

    async def run():
        first = await public_map.build_live_map(None, from_region=1)
        other_mode = await public_map.build_live_map(None, mode="empty", from_region=1)
        other_region = await public_map.build_live_map(None, mode="empty", from_region=2)
        assert first.stats.count == other_mode.stats.count == 1
        assert other_region.stats.count == 2
        assert len(queries) == 2

    asyncio.run(run())


def test_live_map_stats_fall_back_when_redis_is_unavailable(monkeypatch):
    def unavailable():
        raise OSError("Redis unavailable")

    async def stats(_db, **_filters):
        return public_map.LiveMapStats(period_days=30, count=7)

    monkeypatch.setattr(public_map.live_location, "get_redis", unavailable)
    monkeypatch.setattr(public_map, "_stats", stats)
    result = asyncio.run(
        public_map._cached_stats(None, from_region=None, to_region=None, truck_type_id=None)
    )
    assert result.count == 7
