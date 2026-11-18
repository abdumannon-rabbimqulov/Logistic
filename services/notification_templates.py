"""Telegram xabarlari matni va tugmalari — dispatch va boshqa biznes mantiqdan ajratilgan.

Bu yerda faqat SOF funksiyalar: obyektdan matn/klaviatura quriladi, hech narsa
yuborilmaydi va bazaga murojaat yo'q. Sabab: `services/dispatch.py` (1200+ qator)
ichida biznes qoidalar bilan Telegram matnlari aralash edi; matnni o'zgartirish
uchun dispatch'ga tegish kerak bo'lardi. Keyinchalik bu modul notification-service'ga
ko'chadi (docs: 6b-bosqich).
"""

from __future__ import annotations

from typing import Optional

from services import navigation, notifications, pricing

# Taklif / javob holatlari — avval yuborilgan taklif xabari shu matnga tahrirlanadi.
OFFER_ACCEPTED_TEXT = "✅ Siz bu buyurtmani qabul qildingiz!"
OFFER_REJECTED_TEXT = "❌ Siz rad etdingiz"
OFFER_EXPIRED_TEXT = "⏱ Vaqt tugadi — buyurtma boshqa haydovchiga yuborildi"
OFFER_CANCELLED_TEXT = "Bu buyurtma bekor qilindi"

NO_LOCATION_WARNING_TEXT = (
    "📍 Sizga mos yuk chiqdi, lekin joylashuvingiz aniqlanmadi — shuning uchun "
    "taklif yuborilmadi.\n\n"
    "Ilovada GPS'ni yoqing (bosh sahifadagi xarita) yoki \"Liniyaga chiqish\" "
    "oynasida viloyatingizni ko'rsating — shundan keyin yuklar sizga ham taklif qilinadi."
)


def _addr(point) -> str:
    return point.address if point is not None and point.address else "?"


# ── Haydovchiga ─────────────────────────────────────────────────────────────


def offer_text(order, attempt, *, max_rounds: int) -> str:
    distance_note = f"\n📍 Sizgacha: ~{attempt.distance_km} km" if attempt.distance_km is not None else ""
    return (
        f"🚚 Yangi buyurtma taklifi ({attempt.round_number}/{max_rounds})\n"
        f"Yuk: {order.cargo_name} ({order.weight}t)\n"
        f"{_addr(order.origin)} → {_addr(order.destination)}\n"
        f"Masofa: {order.total_distance_km} km\n"
        f"💰 Narx: {order.price} {order.currency}"
        f"{distance_note}\n\n"
        f"⏱ 60 soniya ichida javob bering"
    )


def offer_keyboard(attempt_id: int) -> dict:
    return notifications.inline_keyboard(
        [[("✅ Qabul qilish", f"dispatch:accept:{attempt_id}"), ("❌ Rad etish", f"dispatch:reject:{attempt_id}")]]
    )


def navigation_message(order) -> Optional[tuple[str, dict]]:
    """Qabul qilingandan keyingi navigatsiya xabari; koordinata bo'lmasa `None`.

    Marshrut bizning ilovada chizilmaydi — haydovchi tugmani bosib o'zi odatlangan
    ilovasida (Yandex/Google) ochadi.
    """
    origin, destination = order.origin, order.destination
    keyboard = notifications.url_keyboard(
        [
            [
                ("🧭 Yuk olish joyiga (Yandex)", navigation.yandex_point_url(origin)),
                ("🧭 Google", navigation.google_point_url(origin)),
            ],
            [
                ("🗺 To'liq marshrut (Yandex)", navigation.yandex_route_url(origin, destination)),
                ("🗺 Google", navigation.google_route_url(origin, destination)),
            ],
        ]
    )
    if keyboard is None:
        return None
    text = (
        f"📍 Yuk olish: {_addr(origin)}\n🏁 Yetkazish: {_addr(destination)}\n\n"
        "Marshrutni quyidagi tugmalar orqali o'zingizga qulay ilovada oching:"
    )
    return text, keyboard


def departure_due_text(order, pickup_address: Optional[str]) -> str:
    return (
        f"⏰ '{order.cargo_name}' buyurtmasi uchun yo'lga chiqish vaqti yaqinlashdi.\n"
        f"Yuk ortish nuqtasi: {pickup_address or 'manzil ko‘rsatilmagan'}\n"
        "Yo'lga chiqayotganda ilovada \"Start\" tugmasini bosing."
    )


def manually_assigned_text(order) -> str:
    return f"📦 Sizga admin tomonidan '{order.cargo_name}' buyurtmasi biriktirildi."


# ── Senderga ────────────────────────────────────────────────────────────────


def driver_found_text(order, driver) -> str:
    return f"✅ '{order.cargo_name}' buyurtmangiz uchun haydovchi topildi! ({driver.truck_number})"


def price_bump_text(order) -> str:
    # Nomzod umuman topilmagan bo'lsa raund soni 0 bo'lishi mumkin — "0 ta haydovchi
    # javob bermadi" degan g'alati matn chiqmasligi uchun ikki xil jumla.
    if order.dispatch_round > 0:
        reason = (
            f"'{order.cargo_name}' buyurtmangiz uchun {order.dispatch_round} ta "
            "haydovchidan hech biri javob bermadi."
        )
    else:
        reason = f"'{order.cargo_name}' buyurtmangiz uchun mos haydovchi topilmadi."
    return (
        f"😔 {reason}\n\nJoriy narx: {order.price} {order.currency}\n"
        f"Narxni oshirib qidiruvni davom ettiramizmi?"
    )


def price_bump_keyboard(order) -> dict:
    """"Haydovchi topilmadi" xabarining tugmalari: narxni oshirish yoki bekor qilish.

    Bot handleri (`handlers/dispatch.py`) bekor qilishdan voz kechilganda shu
    klaviaturani qayta tiklaydi. 5 ta belgilangan variant — WebApp'dagi narx tahrirlash
    ekrani bilan aynan bir xil ro'yxat (`services/pricing.py`). Oxirgi qator — voz
    kechish yo'li: narx oshirish yagona chiqish bo'lib qolmasligi kerak.
    """
    return notifications.inline_keyboard(
        [
            [(
                f"+{option['increment']:,.0f} ({option['price']:,.0f} {order.currency})".replace(",", " "),
                f"pricebump:{order.id}:{option['price']}",
            )]
            for option in pricing.quick_price_options(order.price)
        ]
        + [[("❌ Buyurtmani bekor qilish", f"ordercancel:{order.id}")]]
    )
