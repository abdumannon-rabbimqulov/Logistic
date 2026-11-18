"""Buyurtma biznes-amallari (orkestratsiya qatlami).

Qatlamlar (yuqoridan pastga, faqat bir tomonga import qilinadi):
    order/router.py  →  order/service.py  →  services/dispatch.py  →  order/crud.py
                                                                  →  services/order_flow.py
`order/crud.py` — faqat ma'lumot (SQL) qatlami: u dispatch'ni BILMAYDI. Ilgari
`crud.create_order` ichida `services.dispatch` funksiya ichidagi kech import bilan
chaqirilardi (dispatch esa o'z navbatida crud'ni import qiladi) — aylanma bog'liqlik.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from order import crud
from order.models import Order
from order.schemas import OrderCreate
from services import dispatch as dispatch_service

logger = logging.getLogger(__name__)


async def create_order(db: AsyncSession, data: OrderCreate, *, customer_id: int) -> Order:
    """Buyurtmani yaratadi va avtomatik qidiruvni boshlaydi.

    Qidiruv xatoga uchrasa ham buyurtma yaratilishi buzilmaydi — u PENDING holatda
    qoladi va worker'dagi davriy sweep keyinroq qayta urinadi.
    """
    order = await crud.create_order(db, data, customer_id=customer_id)

    order_id = order.id
    try:
        await dispatch_service.start_dispatch(db, order)
    except Exception:
        logger.exception("Order #%s uchun dispatch boshlanmadi", order_id)
        # rollback order obyektining BARCHA atributlarini expired qiladi — chaqiruvchi uni
        # sinxron serializatsiya qilsa MissingGreenlet chiqadi. Shuning uchun qayta yuklanadi.
        await db.rollback()
        order = await crud.get_order(db, order_id) or order
    return order


async def set_custom_price(db: AsyncSession, order: Order, new_price: Decimal) -> Order:
    """Sender narxni o'zgartiradi — faqat qidiruv to'xtagan paytda.

    `dispatch.ensure_price_editable` qidiruv ketayotgan bo'lsa `DispatchError`
    tashlaydi (haydovchi qo'lidagi eski narxli taklifni qabul qilib yubormasligi uchun).
    """
    await dispatch_service.ensure_price_editable(db, order)
    return await crud.set_custom_price(db, order, new_price)
