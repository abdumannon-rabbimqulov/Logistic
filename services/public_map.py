"""Sender va driver uchun jonli yuk xaritasi (`GET /orders/live-map`).

Admin monitoringidan (Admin_panel/router.py `admin_drivers_monitor`) farqi — bu xarita
HAMMA foydalanuvchiga ochiq, shuning uchun:

* haydovchi ismi, davlat raqami, telefon, user/driver/order ID lari, nuqta kontaktlari
  umuman qaytarilmaydi (sxema: `order.schemas.LiveMapItem`);
* Redis'dagi jonli payload'dan (unda `full_name`, `truck_number` bor) FAQAT koordinata olinadi;
* marker ID — driver_id dan HMAC qilingan token: frontend markerni so'rovlar orasida
  kuzata oladi, lekin haqiqiy ID ni tiklab bo'lmaydi.

Filterlar:
* `mode`: `in_transit` (IN_PROGRESS — yuk olingan, yo'lda) | `empty` (onlayn, faol
  buyurtmasiz haydovchilar) | `all`.
* `from_region` / `to_region`: yuk olish / tushirish nuqtasining viloyati
  (`order_waypoints.region_id`). Bo'sh mashina uchun `from_region` — u hozir turgan viloyat.
* `truck_type_id`.

Natija Redis'da qisqa muddat keshlanadi — xaritani ko'p foydalanuvchi bir vaqtda ochib,
har 10 soniyada yangilasa ham DB'ga bitta so'rov tushadi.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config.config import SECRET_KEY
from driver.models import Driver, TruckType
from order.models import Order, OrderStatus, OrderWaypoint, WaypointType
from order.schemas import LiveMapItem, LiveMapResponse, LiveMapStats
from services import live_location, regions

logger = logging.getLogger(__name__)

Mode = Literal["in_transit", "empty", "all"]

CACHE_TTL_SEC = 5
STATS_PERIOD_DAYS = 30
# Jonli translyatsiya bo'lmasa, yo'ldagi mashina uchun DB'dagi oxirgi nuqta shuncha
# eskirmagan bo'lsa ko'rsatiladi (aks holda marker noto'g'ri joyda "qotib" turadi).
LAST_KNOWN_MAX_AGE = timedelta(hours=6)

_ACTIVE_STATUSES = (OrderStatus.SCHEDULED, OrderStatus.ACCEPTED, OrderStatus.IN_PROGRESS)


def marker_id_for(driver_id: int) -> str:
    digest = hmac.new(SECRET_KEY.encode(), f"live-map:{driver_id}".encode(), hashlib.sha256)
    return digest.hexdigest()[:16]


def _money(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _pickup(order: Order) -> Optional[OrderWaypoint]:
    wps = list(order.waypoints)
    return next((w for w in wps if w.type == WaypointType.PICKUP), wps[0] if wps else None)


def _delivery(order: Order) -> Optional[OrderWaypoint]:
    wps = list(order.waypoints)
    return next((w for w in reversed(wps) if w.type == WaypointType.DELIVERY), wps[-1] if wps else None)


def _wp_region(wp: Optional[OrderWaypoint]) -> Optional[int]:
    if wp is None:
        return None
    if wp.region_id is not None:
        return wp.region_id
    # Backfill qilinmagan eski yozuvlar uchun zaxira
    return regions.region_for_point(wp.latitude, wp.longitude)


def _f(value) -> Optional[float]:
    return float(value) if value is not None else None


def _region_filters(from_region: Optional[int], to_region: Optional[int]) -> list:
    """Order bo'yicha SQL shartlari: PICKUP/DELIVERY nuqtasi berilgan viloyatda."""
    conds = []
    if from_region is not None:
        conds.append(
            exists().where(
                OrderWaypoint.order_id == Order.id,
                OrderWaypoint.type == WaypointType.PICKUP,
                OrderWaypoint.region_id == from_region,
            )
        )
    if to_region is not None:
        conds.append(
            exists().where(
                OrderWaypoint.order_id == Order.id,
                OrderWaypoint.type == WaypointType.DELIVERY,
                OrderWaypoint.region_id == to_region,
            )
        )
    return conds


async def _stats(
    db: AsyncSession,
    *,
    from_region: Optional[int],
    to_region: Optional[int],
    truck_type_id: Optional[int],
) -> LiveMapStats:
    since = datetime.now(timezone.utc) - timedelta(days=STATS_PERIOD_DAYS)
    conds = [
        or_(
            Order.status.in_([OrderStatus.ACCEPTED, OrderStatus.IN_PROGRESS]),
            and_(Order.status == OrderStatus.COMPLETED, Order.completed_at >= since),
        ),
        *_region_filters(from_region, to_region),
    ]
    if truck_type_id is not None:
        conds.append(Order.required_truck_type_id == truck_type_id)

    row = (
        await db.execute(
            select(
                func.count(Order.id),
                func.min(Order.price),
                func.avg(Order.price),
                func.max(Order.price),
                func.avg(Order.price / func.nullif(Order.weight, 0)),
                func.avg(Order.weight),
            ).where(*conds)
        )
    ).one()
    count, min_p, avg_p, max_p, avg_per_ton, avg_w = row
    return LiveMapStats(
        period_days=STATS_PERIOD_DAYS,
        count=int(count or 0),
        min_price=_money(min_p),
        avg_price=_money(avg_p),
        max_price=_money(max_p),
        avg_price_per_ton=_money(avg_per_ton),
        avg_weight=Decimal(avg_w).quantize(Decimal("0.1")) if avg_w is not None else None,
    )


async def _live_points() -> dict[int, tuple[float, float]]:
    """driver_id -> (lat, lon). Redis payload'idagi boshqa maydonlar ATAYLAB tashlanadi."""
    points: dict[int, tuple[float, float]] = {}
    try:
        for entry in await live_location.get_all_online_drivers():
            try:
                lat, lon = float(entry["lat"]), float(entry["lon"])
                if entry.get("stopped") or (lat == 0.0 and lon == 0.0):
                    continue
                points[int(entry["driver_id"])] = (lat, lon)
            except (KeyError, TypeError, ValueError):
                continue
    except Exception:
        logger.exception("Jonli lokatsiyalarni olishda xato (live-map)")
    return points


async def _in_transit_items(
    db: AsyncSession,
    live: dict[int, tuple[float, float]],
    *,
    from_region: Optional[int],
    to_region: Optional[int],
    truck_type_id: Optional[int],
) -> list[LiveMapItem]:
    conds = [
        Order.status == OrderStatus.IN_PROGRESS,
        Order.driver_id.is_not(None),
        *_region_filters(from_region, to_region),
    ]
    if truck_type_id is not None:
        conds.append(Order.required_truck_type_id == truck_type_id)

    orders = (
        await db.execute(
            select(Order)
            .options(
                selectinload(Order.waypoints),
                selectinload(Order.truck_type),
                selectinload(Order.driver),
            )
            .where(*conds)
            .order_by(Order.id)
        )
    ).scalars().unique().all()

    now = datetime.now(timezone.utc)
    items: list[LiveMapItem] = []
    seen_drivers: set[int] = set()
    for order in orders:
        driver: Optional[Driver] = order.driver
        if driver is None or driver.id in seen_drivers:
            continue
        point = live.get(driver.id)
        if point is None and driver.last_latitude is not None and driver.last_longitude is not None:
            fresh = driver.last_location_at is not None and now - driver.last_location_at <= LAST_KNOWN_MAX_AGE
            if fresh:
                point = (float(driver.last_latitude), float(driver.last_longitude))
        if point is None:
            continue
        seen_drivers.add(driver.id)

        tt: Optional[TruckType] = order.truck_type
        pickup, delivery = _pickup(order), _delivery(order)
        weight = order.weight
        max_w = tt.max_weight if tt else None
        load_percent = (
            int((Decimal(weight) / Decimal(max_w) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if weight is not None and max_w
            else None
        )
        items.append(
            LiveMapItem(
                marker_id=marker_id_for(driver.id),
                lat=point[0],
                lon=point[1],
                has_cargo=True,
                truck_type_id=tt.id if tt else None,
                truck_type_name=tt.name if tt else None,
                truck_type_image_url=tt.image_url if tt else None,
                truck_max_weight=max_w,
                current_region=regions.region_name(regions.region_for_point(*point)),
                cargo_name=order.cargo_name,
                weight=weight,
                load_percent=load_percent,
                pickup_address=pickup.address if pickup else None,
                pickup_lat=_f(pickup.latitude) if pickup else None,
                pickup_lon=_f(pickup.longitude) if pickup else None,
                pickup_region=regions.region_name(_wp_region(pickup)),
                delivery_address=delivery.address if delivery else None,
                delivery_lat=_f(delivery.latitude) if delivery else None,
                delivery_lon=_f(delivery.longitude) if delivery else None,
                delivery_region=regions.region_name(_wp_region(delivery)),
                distance_km=Decimal(order.billable_distance_km)
                if order.billable_distance_km is not None
                else order.total_distance_km,
                price=_money(order.price),
                price_per_ton=_money(order.price / weight) if weight else None,
                currency=order.currency or "UZS",
            )
        )
    return items


async def _empty_items(
    db: AsyncSession,
    live: dict[int, tuple[float, float]],
    *,
    from_region: Optional[int],
    truck_type_id: Optional[int],
) -> list[LiveMapItem]:
    """Onlayn (jonli translyatsiya qilayotgan), faol buyurtmasiz haydovchilar."""
    if not live:
        return []
    busy = exists().where(Order.driver_id == Driver.id, Order.status.in_(_ACTIVE_STATUSES))
    conds = [Driver.id.in_(list(live.keys())), Driver.is_blocked.is_(False), ~busy]
    if truck_type_id is not None:
        conds.append(Driver.truck_type_id == truck_type_id)

    rows = (
        await db.execute(
            select(Driver.id, TruckType)
            .outerjoin(TruckType, Driver.truck_type_id == TruckType.id)
            .where(*conds)
            .order_by(Driver.id)
        )
    ).all()

    items: list[LiveMapItem] = []
    for driver_id, tt in rows:
        lat, lon = live[driver_id]
        region_id = regions.region_for_point(lat, lon)
        if from_region is not None and region_id != from_region:
            continue
        items.append(
            LiveMapItem(
                marker_id=marker_id_for(driver_id),
                lat=lat,
                lon=lon,
                has_cargo=False,
                truck_type_id=tt.id if tt else None,
                truck_type_name=tt.name if tt else None,
                truck_type_image_url=tt.image_url if tt else None,
                truck_max_weight=tt.max_weight if tt else None,
                current_region=regions.region_name(region_id),
            )
        )
    return items


def _cache_key(mode: str, from_region, to_region, truck_type_id) -> str:
    return f"live_map:v1:{mode}:{from_region or '-'}:{to_region or '-'}:{truck_type_id or '-'}"


async def build_live_map(
    db: AsyncSession,
    *,
    mode: Mode = "in_transit",
    from_region: Optional[int] = None,
    to_region: Optional[int] = None,
    truck_type_id: Optional[int] = None,
) -> LiveMapResponse:
    key = _cache_key(mode, from_region, to_region, truck_type_id)
    try:
        cached = await live_location.get_redis().get(key)
        if cached:
            return LiveMapResponse.model_validate_json(cached)
    except Exception:
        logger.debug("live-map keshini o'qib bo'lmadi", exc_info=True)

    live = await _live_points()
    items: list[LiveMapItem] = []
    if mode in ("in_transit", "all"):
        items += await _in_transit_items(
            db, live, from_region=from_region, to_region=to_region, truck_type_id=truck_type_id
        )
    if mode in ("empty", "all"):
        items += await _empty_items(db, live, from_region=from_region, truck_type_id=truck_type_id)

    stats = await _stats(db, from_region=from_region, to_region=to_region, truck_type_id=truck_type_id)
    response = LiveMapResponse(items=items, stats=stats, generated_at=datetime.now(timezone.utc))

    try:
        await live_location.get_redis().set(key, response.model_dump_json(), ex=CACHE_TTL_SEC)
    except Exception:
        logger.debug("live-map keshini yozib bo'lmadi", exc_info=True)
    return response

