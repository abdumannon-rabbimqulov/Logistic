from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from driver.models import Driver, TruckType
from order.dispatch_models import DispatchAttempt, DispatchAttemptStatus
from order.models import Order, OrderRoutePostGIS, OrderStatus, OrderWaypoint
from order.schemas import OrderCreate, PriceEstimateRequest, OrderUpdate, OrderWaypointCreate
from services import billing, order_flow, osrm_client, outbox, pricing, queue, regions, yandex_geocoder
from utils.geo import simplify_polyline

logger = logging.getLogger(__name__)


def _overload_warning(data: OrderCreate, truck_type: TruckType) -> Optional[str]:
    """Yuk og'irligi/hajmi tanlangan mashina sig'imidan oshsa ogohlantirish matni qaytaradi.

    Majburiy taqiq YO'Q — O'zbekiston bozorida haydovchilar ko'pincha e'lon qilingan
    sig'imdan ortiqni ham qabul qiladi. Faqat ko'rinadigan ogohlantirish beriladi.
    """
    parts: list[str] = []
    if data.weight is not None and data.weight > truck_type.max_weight:
        parts.append(f"og'irlik {data.weight}t > {truck_type.max_weight}t")
    if data.volume is not None and truck_type.max_volume is not None and data.volume > truck_type.max_volume:
        parts.append(f"hajm {data.volume}m³ > {truck_type.max_volume}m³")
    if not parts:
        return None
    return "Tanlangan mashina (" + truck_type.name + ") sig'imidan oshadi: " + ", ".join(parts)


async def _resolve_location(
    address: Optional[str], latitude: Optional[Decimal], longitude: Optional[Decimal]
) -> tuple[Optional[str], float, float]:
    """(address, latitude, longitude) — yetishmagan tomonini to'ldiradi.

    - Koordinata berilgan bo'lsa (masalan sender Telegram orqali o'z joylashuvini yuborgan) —
      koordinata ustuvor, manzil matni bo'lmasa reverse-geocoding bilan topiladi.
    - Faqat manzil matni berilgan bo'lsa — Yandex Geocoder orqali qidirilib, eng mos
      (birinchi) natijaning koordinatasi olinadi.
    """
    if latitude is not None and longitude is not None:
        lat, lon = float(latitude), float(longitude)
        if not address:
            address = await yandex_geocoder.reverse_geocode(lat, lon)
        return address, lat, lon

    candidates = await yandex_geocoder.search_address(address or "")
    if not candidates:
        raise ValueError(f"Manzil topilmadi: '{address}'")
    best = candidates[0]
    return best.address, best.latitude, best.longitude


async def _resolve_waypoint_location(wp: OrderWaypointCreate) -> tuple[Optional[str], float, float]:
    return await _resolve_location(wp.address, wp.latitude, wp.longitude)


async def create_order(db: AsyncSession, data: OrderCreate, *, customer_id: int) -> Order:
    truck_type = await db.get(TruckType, data.required_truck_type_id)
    if not truck_type or not truck_type.is_active:
        raise ValueError("Ko'rsatilgan mashina turi topilmadi yoki faol emas")

    # Har bir waypoint mustaqil ravishda geocode qilinadi — ketma-ket kutish o'rniga
    # parallel yuborish umumiy javob vaqtini (N ta manzil bo'lsa ham) bitta so'rovga tenglashtiradi.
    resolved: list[tuple[Optional[str], float, float]] = list(
        await asyncio.gather(*(_resolve_waypoint_location(wp) for wp in data.waypoints))
    )

    # Narx masofaga bog'liq bo'lgani uchun marshrutsiz buyurtma yaratib bo'lmaydi —
    # avval mijozdan qo'lda qabul qilingan `price` shu yerda ishonchsiz manba edi.
    try:
        route = await osrm_client.get_route([(lat, lon) for _, lat, lon in resolved])
    except osrm_client.OSRMNoRouteError as exc:
        # Nuqtalar yo'ldan uzoq — mijoz boshqa manzil tanlashi kerak (422).
        # OSRMUnavailableError esa ushlanmaydi: u infratuzilma nosozligi, router 503 qaytaradi.
        raise ValueError(f"Bu manzillar orasida yo'l topilmadi, buyurtma yaratilmadi: {exc}") from exc

    distance_km = Decimal(str(route.distance_km))
    # Narx 5 km qadamiga yaxlitlangan masofadan hisoblanadi (services/pricing.py),
    # `total_distance_km` esa OSRM bergan aniq masofa bo'lib qoladi.
    billable_distance_km = pricing.round_distance_km(distance_km)
    price = truck_type.calculate_price(distance_km, data.weight)

    order = Order(
        customer_id=customer_id,
        cargo_name=data.cargo_name,
        weight=data.weight,
        volume=data.volume,
        pickup_at=data.pickup_at,
        unloading_mode=data.unloading_mode,
        unloading_wait_hours=data.unloading_wait_hours,
        required_truck_type_id=data.required_truck_type_id,
        price=price,
        base_price=price,
        currency="UZS",
        total_distance_km=distance_km,
        billable_distance_km=billable_distance_km,
        overload_warning=_overload_warning(data, truck_type),
        route=OrderRoutePostGIS(geom_route=WKTElement(route.geometry_wkt, srid=4326)),
        waypoints=[
            OrderWaypoint(
                sequence=wp.sequence,
                type=wp.type,
                address=address,
                latitude=Decimal(str(lat)),
                longitude=Decimal(str(lon)),
                region_id=regions.region_for_point(lat, lon),
                contact_name=wp.contact_name,
                contact_phone=wp.contact_phone,
            )
            for wp, (address, lat, lon) in zip(data.waypoints, resolved)
        ],
    )

    db.add(order)
    await db.commit()
    await db.refresh(order, attribute_names=["waypoints", "route"])
    # Qidiruvni boshlash — `order/service.py: create_order` (crud dispatch'ni bilmaydi).
    return order


async def get_order(db: AsyncSession, order_id: int) -> Optional[Order]:
    # `driver`->`user`, `customer` va `truck_type` ham shu yerda eager-load qilinadi:
    # `OrderDetailResponse.from_order` sender/haydovchi kontakt kartochkasi va mashina
    # nomini shu obyektlardan o'qiydi — lazy-load async kontekstda MissingGreenlet
    # bilan yiqilardi.
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.waypoints),
            selectinload(Order.route),
            selectinload(Order.driver).selectinload(Driver.user),
            selectinload(Order.customer),
            selectinload(Order.truck_type),
        )
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def list_orders_by_customer(db: AsyncSession, customer_id: int, *, skip: int = 0, limit: int = 100) -> Sequence[Order]:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.waypoints))
        .where(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def list_orders_by_driver(db: AsyncSession, driver_id: int, *, skip: int = 0, limit: int = 100) -> Sequence[Order]:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.waypoints))
        .where(Order.driver_id == driver_id)
        .order_by(Order.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def list_available_orders(
    db: AsyncSession, *, truck_type_id: Optional[int] = None, skip: int = 0, limit: int = 100
) -> Sequence[Order]:
    """Hali haydovchisi biriktirilmagan, PENDING holatdagi buyurtmalar (haydovchi ilovasi uchun)."""
    query = (
        select(Order)
        .options(selectinload(Order.waypoints))
        .where(Order.status == OrderStatus.PENDING, Order.driver_id.is_(None))
        .order_by(Order.created_at.desc())
    )
    if truck_type_id is not None:
        query = query.where(Order.required_truck_type_id == truck_type_id)
    result = await db.execute(query.offset(skip).limit(limit))
    return result.scalars().all()


async def recalc_price_for_cargo(
    db: AsyncSession,
    order: Order,
    *,
    weight: Optional[Decimal] = None,
    truck_type_id: Optional[int] = None,
) -> Optional[dict]:
    """Og'irlik yoki mashina turi o'zgarganda narxni qayta hisoblaydi.

    Faqat haydovchi hali biriktirilmagan (PENDING) buyurtmalar uchun: kelishilgan
    narxni keyin jimgina o'zgartirib bo'lmaydi. Sender qo'shgan ustama
    (`price - base_price`) saqlanadi — u narxni oshirgan bo'lsa, yangi og'irlik
    bilan ham shuncha yuqori qoladi.

    Qaytaradi: `{"price", "base_price"}` yoki o'zgartirish kerak bo'lmasa `None`.
    """
    if order.status != OrderStatus.PENDING or order.total_distance_km is None:
        return None
    tt = await db.get(TruckType, truck_type_id or order.required_truck_type_id)
    if tt is None:
        return None
    new_base = tt.calculate_price(order.total_distance_km, weight if weight is not None else order.weight)
    old_base = order_base_price(order)
    markup = max(Decimal(0), (order.price or old_base) - old_base)
    return {"base_price": new_base, "price": new_base + markup}


async def update_order(db: AsyncSession, order: Order, data: OrderUpdate) -> Order:
    values = data.model_dump(exclude_unset=True)
    if "weight" in values or "required_truck_type_id" in values:
        if "required_truck_type_id" in values:
            tt = await db.get(TruckType, values["required_truck_type_id"])
            if not tt or not tt.is_active:
                raise ValueError("Ko'rsatilgan mashina turi topilmadi yoki faol emas")
        repriced = await recalc_price_for_cargo(
            db, order, weight=values.get("weight"), truck_type_id=values.get("required_truck_type_id")
        )
        if repriced:
            values.update(repriced)
    if values:
        await db.execute(update(Order).where(Order.id == order.id).values(**values))
        await db.commit()
        await db.refresh(order, attribute_names=[*values.keys(), "updated_at"])
    return order


# Status o'zgartirish va uning hodisasi — holat mashinasi bilan birga
# `services/order_flow.py` da. Bu yerda eski nomlar saqlanadi (chaqiruvchilar uchun).
record_status_changed = order_flow.record_status_changed
record_order_status_changed = order_flow.record_order_status_changed
update_order_status = order_flow.change_order_status


async def assign_driver(
    db: AsyncSession,
    order: Order,
    driver_id: int,
    *,
    actor_user_id: Optional[int] = None,
    actor_role: Optional[str] = None,
) -> Optional[Order]:
    """Haydovchini biriktiradi — atomik (`WHERE driver_id IS NULL`), shuning uchun bir
    vaqtda kelgan ikkinchi so'rov 0 qator yangilaydi va `None` qaytaradi (409 uchun)."""
    old_status = order.status
    result = await db.execute(
        update(Order)
        .where(Order.id == order.id, Order.driver_id.is_(None))
        .values(driver_id=driver_id, status=OrderStatus.ACCEPTED)
    )
    if result.rowcount == 0:
        await db.rollback()
        return None
    record_status_changed(
        db,
        order_id=order.id,
        customer_id=order.customer_id,
        driver_id=driver_id,
        old_status=old_status,
        new_status=OrderStatus.ACCEPTED,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
    )
    await db.commit()
    await db.refresh(order, attribute_names=["driver_id", "status", "updated_at"])
    return order


async def cancel_order(
    db: AsyncSession,
    order: Order,
    *,
    cancelled_by_user_id: int,
    reason: Optional[str] = None,
) -> Order:
    """Buyurtmani CANCELLED holatiga o'tkazadi (ilgari bu qattiq DELETE edi).

    Qattiq o'chirishda buyurtma, uning nuqtalari va barcha dispatch urinishlari izsiz
    yo'qolardi: bekor qilish tarixi qolmasdi, admin statistikasida `CANCELLED` hech
    qachon ko'rinmasdi va "nega bu yuk tashlab yuborilgan?" degan savolga javob yo'q edi.

    Kutilayotgan dispatch urinishlari ham yopiladi — aks holda haydovchi allaqachon
    bekor qilingan buyurtmani qabul qilib yuborishi mumkin.
    """
    # Allaqachon bekor qilingan bo'lsa — hech narsaga tegilmaydi. Bu shunchaki
    # optimizatsiya emas: takroriy so'rov asl sabab va vaqtni ustiga yozib yuborardi,
    # ya'ni bekor qilish tarixi (bu o'zgarishning asosiy maqsadi) yo'qolardi.
    if order.status == OrderStatus.CANCELLED:
        return order

    order_flow.ensure_order_transition_allowed(order.status, OrderStatus.CANCELLED)
    old_status = order.status

    await db.execute(
        update(DispatchAttempt)
        .where(
            DispatchAttempt.order_id == order.id,
            DispatchAttempt.status == DispatchAttemptStatus.PENDING,
        )
        .values(status=DispatchAttemptStatus.CANCELLED)
    )

    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(timezone.utc)
    order.cancelled_by_user_id = cancelled_by_user_id
    order.cancel_reason = reason
    record_order_status_changed(db, order, old_status, actor_user_id=cancelled_by_user_id)
    await db.commit()
    await db.refresh(
        order,
        attribute_names=["status", "cancelled_at", "cancelled_by_user_id", "cancel_reason", "updated_at"],
    )
    return order


async def estimate_price(db: AsyncSession, data: PriceEstimateRequest) -> dict:
    """Pickup/delivery manzillari bo'yicha masofani hisoblab, barcha aktiv mashina
    turlari uchun narxni qaytaradi (mijoz mashina tanlashdan oldin ko'radi)."""
    (origin_address, origin_lat, origin_lon), (dest_address, dest_lat, dest_lon) = await asyncio.gather(
        _resolve_location(data.origin.address, data.origin.latitude, data.origin.longitude),
        _resolve_location(data.destination.address, data.destination.latitude, data.destination.longitude),
    )

    try:
        route = await osrm_client.get_route([(origin_lat, origin_lon), (dest_lat, dest_lon)])
    except osrm_client.OSRMNoRouteError as exc:
        raise ValueError(f"Bu manzillar orasida yo'l topilmadi: {exc}") from exc

    distance_km = Decimal(str(route.distance_km))
    billable_distance_km = pricing.round_distance_km(distance_km)

    result = await db.execute(select(TruckType).where(TruckType.is_active.is_(True)))
    truck_types = result.scalars().all()

    # Chegirma chegarasi bir marta o'qiladi — har bir variant uchun qayta so'rov shart emas.
    max_discount_percent = await pricing.get_sender_max_discount_percent(db)

    def _option(tt: TruckType) -> dict:
        price = tt.calculate_price(distance_km, data.weight)
        return {
            "truck_type_id": tt.id,
            "name": tt.name,
            "image_url": tt.image_url,
            "price": price,
            "min_allowed_price": pricing.min_allowed_price(price, max_discount_percent),
            "quick_price_options": pricing.quick_price_options(price),
        }

    options = sorted((_option(tt) for tt in truck_types), key=lambda o: o["price"])

    return {
        "origin_address": origin_address,
        "origin_latitude": origin_lat,
        "origin_longitude": origin_lon,
        "destination_address": dest_address,
        "destination_latitude": dest_lat,
        "destination_longitude": dest_lon,
        "distance_km": distance_km,
        "billable_distance_km": billable_distance_km,
        "duration_min": Decimal(str(route.duration_min)),
        # To'liq geometriya bazaga saqlanadigan aniqlikda — xaritada ko'rsatish uchun
        # shuncha nuqta shart emas, shuning uchun javob hajmi soddalashtirib kichraytiriladi.
        "route_geometry": simplify_polyline(route.geometry),
        "options": options,
        "max_discount_percent": max_discount_percent,
    }


def order_base_price(order: Order) -> Decimal:
    """Chegirma hisoblanadigan anchor narx.

    Eski buyurtmalarda (migratsiyadan oldingi) `base_price` NULL bo'lishi mumkin —
    u holda tahrirlanmagan asl narxga eng yaqin qiymat ishlatiladi.
    """
    return order.base_price or order.original_price or order.price


async def get_order_price_options(db: AsyncSession, order: Order) -> dict:
    """Narx tahrirlash ekrani uchun: anchor narx, chegara va 5 ta tez variant."""
    base_price = order_base_price(order)
    max_discount_percent = await pricing.get_sender_max_discount_percent(db)
    return {
        "order_id": order.id,
        "currency": order.currency,
        "base_price": base_price,
        "current_price": order.price,
        "min_allowed_price": pricing.min_allowed_price(base_price, max_discount_percent),
        "max_discount_percent": max_discount_percent,
        "quick_price_options": pricing.quick_price_options(order.price),
    }


async def set_custom_price(db: AsyncSession, order: Order, new_price: Decimal) -> Order:
    """Sender belgilagan narxni buyurtmaga yozadi.

    Oshirish cheklanmagan, pasaytirish esa `SENDER_MAX_DISCOUNT_PERCENT` bilan
    chegaralangan — chegaradan past narx `pricing.PriceValidationError` ko'taradi
    (router 400 ga aylantiradi).

    Narx faqat haydovchi biriktirilgunga qadar o'zgartiriladi: kelishilgan narxni
    yo'lda o'zgartirish haydovchi uchun bir tomonlama zarar bo'lardi.

    Qidiruv KETAYOTGAN paytda o'zgartirib bo'lmasligini `order/service.py:
    set_custom_price` tekshiradi (`dispatch.ensure_price_editable`) — bu funksiya
    faqat ma'lumot qatlami.
    """
    if order.driver_id is not None or order.status != OrderStatus.PENDING:
        raise ValueError("Narxni faqat haydovchi biriktirilmagan (PENDING) buyurtmada o'zgartirish mumkin")

    base_price = order_base_price(order)
    price = await pricing.validate_custom_price_for_db(db, new_price, base_price)

    if order.base_price is None:
        order.base_price = base_price
    if order.original_price is None and price != order.price:
        order.original_price = order.price
    order.price = price
    await db.commit()
    await db.refresh(order, attribute_names=["price", "base_price", "original_price", "updated_at"])
    return order


async def get_order_route_geometry(db: AsyncSession, order_id: int) -> list[tuple[float, float]]:
    """Buyurtmaning saqlangan marshrut chizig'i: [(latitude, longitude), ...].

    Geometriya buyurtma yaratilganda OSRM'dan olinib PostGIS'ga yozilgan
    (`OrderRoutePostGIS.geom_route`) — bu yerda u qaytadan hisoblanmaydi, faqat
    o'qiladi. `ST_AsGeoJSON` koordinatalarni [lon, lat] tartibida beradi, xarita
    kutubxonalari esa (lat, lon) kutadi — shu sabab almashtiriladi.

    Marshruti yo'q (eski yoki nuqson bilan yaratilgan) buyurtma uchun bo'sh ro'yxat
    qaytadi: xaritada chiziq chizilmaydi, lekin A/B belgilari baribir ko'rinadi.
    """
    result = await db.execute(
        select(func.ST_AsGeoJSON(OrderRoutePostGIS.geom_route)).where(
            OrderRoutePostGIS.order_id == order_id
        )
    )
    raw = result.scalar_one_or_none()
    if not raw:
        return []
    try:
        coordinates = json.loads(raw).get("coordinates", [])
    except (ValueError, AttributeError):
        logger.warning("Buyurtma %s marshrut geometriyasi o'qilmadi", order_id)
        return []

    # Bazadagi geometriya to'liq aniqlikda (minglab nuqta) — javob hajmini kichraytirish
    # uchun xaritada ko'rinishi o'zgarmaydigan darajada soddalashtiriladi.
    return simplify_polyline([(lat, lon) for lon, lat in coordinates])
