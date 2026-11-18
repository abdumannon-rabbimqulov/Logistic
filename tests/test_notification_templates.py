"""Telegram matnlari (sof funksiyalar) — dispatch'dan ajratilgan."""

from decimal import Decimal
from types import SimpleNamespace

from services import dispatch, notification_templates as t


def _order(**kw):
    point = lambda a: SimpleNamespace(address=a, latitude=41.3, longitude=69.2)  # noqa: E731
    base = dict(id=7, cargo_name="Mebel", weight=Decimal("4.5"), origin=point("Toshkent"),
                destination=point("Andijon"), total_distance_km=330, price=Decimal("3000000"),
                currency="UZS", dispatch_round=0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_offer_text_has_route_price_and_round():
    attempt = SimpleNamespace(round_number=2, distance_km=12)
    text = t.offer_text(_order(), attempt, max_rounds=5)
    assert "(2/5)" in text and "Toshkent → Andijon" in text and "3000000 UZS" in text and "~12 km" in text


def test_price_bump_text_zero_rounds_wording():
    assert "mos haydovchi topilmadi" in t.price_bump_text(_order(dispatch_round=0))
    assert "3 ta haydovchidan" in t.price_bump_text(_order(dispatch_round=3))


def test_price_bump_keyboard_still_exported_from_dispatch():
    # handlers/dispatch.py eski nom bilan import qiladi.
    assert dispatch.price_bump_keyboard is t.price_bump_keyboard
    kb = t.price_bump_keyboard(_order())
    assert kb["inline_keyboard"][-1][0]["callback_data"] == "ordercancel:7"
