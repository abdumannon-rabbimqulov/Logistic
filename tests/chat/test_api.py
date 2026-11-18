"""Chat HTTP API: ishtirokchi tekshiruvi, readonly, o'qilgan belgisi, media, hodisalar."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from chat_service import access, domain
from chat_service.events import handle_order_event

from .conftest import DRIVER_ID, DRIVER_USER, SENDER, STRANGER, auth, make_token

ORDER = 42


async def open_chat(*, driver_user_id=DRIVER_USER, at=None):
    data = {"order_id": ORDER, "customer_id": SENDER, "driver_id": DRIVER_ID, "new_status": "ACCEPTED"}
    if driver_user_id is not None:
        data["driver_user_id"] = driver_user_id
    return await handle_order_event(domain.EVENT_ORDER_STATUS_CHANGED, data, at)


async def send(client, user, text="salom", role="sender", **extra):
    body = {"kind": "text", "text": text, **extra}
    return await client.post(f"/chat/orders/{ORDER}/messages", json=body, headers=auth(user, role))


def jpeg_bytes(size=(800, 600)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format="JPEG")
    return out.getvalue()


# --- autentifikatsiya va ishtirokchi --------------------------------------------------


async def test_requires_token(client):
    await open_chat()
    assert (await client.get(f"/chat/orders/{ORDER}")).status_code == 401


async def test_refresh_token_rejected(client):
    await open_chat()
    headers = {"Authorization": f"Bearer {make_token(SENDER, token_type='refresh')}"}
    assert (await client.get(f"/chat/orders/{ORDER}", headers=headers)).status_code == 401


async def test_participants_can_read_and_write(client):
    await open_chat()
    r = await client.get(f"/chat/orders/{ORDER}", headers=auth(SENDER))
    assert r.status_code == 200
    assert r.json()["my_role"] == "sender" and r.json()["peer_user_id"] == DRIVER_USER

    r = await client.get(f"/chat/orders/{ORDER}", headers=auth(DRIVER_USER, "driver"))
    assert r.json()["my_role"] == "driver"

    assert (await send(client, SENDER)).status_code == 201
    assert (await send(client, DRIVER_USER, "kelyapman", role="driver")).status_code == 201

    msgs = (await client.get(f"/chat/orders/{ORDER}/messages", headers=auth(SENDER))).json()["messages"]
    assert [m["text"] for m in msgs] == ["salom", "kelyapman"]


@pytest.mark.parametrize("path", ["", "/messages", "/unread", "/sync"])
async def test_stranger_gets_404_everywhere(client, path):
    await open_chat()
    r = await client.get(f"/chat/orders/{ORDER}{path}", headers=auth(STRANGER, "driver"))
    assert r.status_code == 404
    # Mavjud bo'lmagan chat bilan bir xil javob — buyurtma borligini bilib bo'lmasin.
    r2 = await client.get(f"/chat/orders/999{path}", headers=auth(SENDER))
    assert r2.status_code == 404 and r.json() == r2.json()


async def test_stranger_cannot_write_or_upload(client):
    await open_chat()
    assert (await send(client, STRANGER)).status_code == 404
    files = {"file": ("a.jpg", jpeg_bytes(), "image/jpeg")}
    r = await client.post(
        f"/chat/orders/{ORDER}/media", data={"kind": "photo"}, files=files, headers=auth(STRANGER)
    )
    assert r.status_code == 404


async def test_driver_bound_via_core_when_event_has_no_user_id(client, monkeypatch):
    await open_chat(driver_user_id=None)

    calls = []

    async def fake_lookup(token):
        calls.append(token)
        return DRIVER_ID

    monkeypatch.setattr(access, "core_driver_lookup", fake_lookup)

    # Haydovchi bo'lmagan rol — core'ga so'rov ham yuborilmaydi.
    assert (await client.get(f"/chat/orders/{ORDER}", headers=auth(STRANGER, "sender"))).status_code == 404
    assert calls == []

    r = await client.get(f"/chat/orders/{ORDER}", headers=auth(DRIVER_USER, "driver"))
    assert r.status_code == 200 and r.json()["my_role"] == "driver"
    # Bog'langach boshqa haydovchi kira olmaydi.
    assert (await client.get(f"/chat/orders/{ORDER}", headers=auth(STRANGER, "driver"))).status_code == 404
    assert len(calls) == 1


async def test_other_driver_not_bound(client, monkeypatch):
    await open_chat(driver_user_id=None)

    async def other_driver(token):
        return DRIVER_ID + 100

    monkeypatch.setattr(access, "core_driver_lookup", other_driver)
    assert (await client.get(f"/chat/orders/{ORDER}", headers=auth(STRANGER, "driver"))).status_code == 404


# --- readonly ------------------------------------------------------------------


async def test_readonly_24h_after_completed(client):
    t0 = datetime.now(timezone.utc) - timedelta(hours=30)
    await open_chat(at=t0)
    await send(client, SENDER)  # hali ochiq — oldingi yozishma
    await handle_order_event(
        domain.EVENT_ORDER_STATUS_CHANGED,
        {"order_id": ORDER, "customer_id": SENDER, "driver_id": DRIVER_ID, "new_status": "COMPLETED"},
        t0 + timedelta(hours=1),
    )

    conv = (await client.get(f"/chat/orders/{ORDER}", headers=auth(SENDER))).json()
    assert conv["status"] == "readonly" and conv["write_blocked_reason"]

    r = await send(client, DRIVER_USER, role="driver")
    assert r.status_code == 409
    msgs = (await client.get(f"/chat/orders/{ORDER}/messages", headers=auth(SENDER))).json()["messages"]
    assert len(msgs) == 1  # o'qish mumkin
    mid = msgs[0]["id"]
    assert (await client.patch(f"/chat/orders/{ORDER}/messages/{mid}", json={"text": "x"}, headers=auth(SENDER))).status_code == 409
    assert (await client.delete(f"/chat/orders/{ORDER}/messages/{mid}", headers=auth(SENDER))).status_code == 409
    # O'qilgan belgisi yopilgan chatda ham qo'yiladi.
    r = await client.post(
        f"/chat/orders/{ORDER}/read", json={"last_read_message_id": mid}, headers=auth(DRIVER_USER, "driver")
    )
    assert r.status_code == 200


async def test_still_open_within_24h(client):
    t0 = datetime.now(timezone.utc) - timedelta(hours=3)
    await open_chat(at=t0)
    await handle_order_event(
        domain.EVENT_ORDER_STATUS_CHANGED,
        {"order_id": ORDER, "customer_id": SENDER, "driver_id": DRIVER_ID, "new_status": "COMPLETED"},
        t0 + timedelta(hours=1),
    )
    assert (await send(client, SENDER, "rahmat")).status_code == 201


# --- o'qilgan belgisi ------------------------------------------------------------


async def test_read_marks_and_unread(client, chat_env):
    await open_chat()
    ids = [(await send(client, SENDER, f"m{i}")).json()["id"] for i in range(3)]

    # Yuboruvchining o'zi uchun o'qilmagan yo'q.
    assert (await client.get(f"/chat/orders/{ORDER}/unread", headers=auth(SENDER))).json()["unread_count"] == 0
    drv = auth(DRIVER_USER, "driver")
    assert (await client.get(f"/chat/orders/{ORDER}/unread", headers=drv)).json()["unread_count"] == 3

    r = await client.post(f"/chat/orders/{ORDER}/read", json={"last_read_message_id": ids[1]}, headers=drv)
    assert r.json() == {"order_id": ORDER, "last_read_message_id": ids[1], "unread_count": 1}

    # ✓✓: yuboruvchi sherigining belgisini ko'radi.
    conv = (await client.get(f"/chat/orders/{ORDER}", headers=auth(SENDER))).json()
    assert conv["peer_last_read_id"] == ids[1]

    read_events = [e for uid, e in chat_env["broadcaster"].sent if e["type"] == "message.read"]
    assert {(e["user_id"], e["last_read_message_id"]) for e in read_events} == {(DRIVER_USER, ids[1])}

    # Orqaga qaytmaydi va mavjud bo'lmagan id'ga surilmaydi.
    r = await client.post(f"/chat/orders/{ORDER}/read", json={"last_read_message_id": ids[0]}, headers=drv)
    assert r.json()["last_read_message_id"] == ids[1]
    r = await client.post(f"/chat/orders/{ORDER}/read", json={"last_read_message_id": 10**9}, headers=drv)
    assert r.json()["last_read_message_id"] == ids[2] and r.json()["unread_count"] == 0


async def test_deleted_messages_not_counted_unread(client):
    await open_chat()
    mid = (await send(client, SENDER, "xato")).json()["id"]
    await client.delete(f"/chat/orders/{ORDER}/messages/{mid}", headers=auth(SENDER))
    r = await client.get(f"/chat/orders/{ORDER}/unread", headers=auth(DRIVER_USER, "driver"))
    assert r.json()["unread_count"] == 0


# --- yuborish, reply, tahrir, o'chirish ------------------------------------------------


async def test_message_new_broadcast_and_event(client, chat_env):
    await open_chat()
    r = await send(client, SENDER, "+998 90 123 45 67 ga qo'ng'iroq qiling")
    assert r.status_code == 201
    # Telefon raqamlar yashirilmaydi (talab).
    assert r.json()["text"] == "+998 90 123 45 67 ga qo'ng'iroq qiling"

    new = [(uid, e) for uid, e in chat_env["broadcaster"].sent if e["type"] == "message.new"]
    assert {uid for uid, _ in new} == {SENDER, DRIVER_USER}

    (event, payload), = chat_env["events"]
    assert event == "chat.message_created"
    assert payload["order_id"] == ORDER
    assert payload["sender_user_id"] == SENDER
    assert payload["recipient_user_id"] == DRIVER_USER
    assert payload["recipient_driver_id"] == DRIVER_ID
    assert payload["recipient_online"] is False
    assert payload["preview"].startswith("+998")


async def test_event_carries_driver_id_when_user_unknown(client, chat_env):
    await open_chat(driver_user_id=None)
    await send(client, SENDER)
    (_, payload), = chat_env["events"]
    assert payload["recipient_user_id"] is None and payload["recipient_driver_id"] == DRIVER_ID


async def test_client_id_dedup(client):
    await open_chat()
    r1 = await send(client, SENDER, client_id="c-1")
    r2 = await send(client, SENDER, client_id="c-1")
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


async def test_reply_and_validation(client):
    await open_chat()
    first = (await send(client, SENDER, "manzil qayer?")).json()
    r = await send(client, DRIVER_USER, "Chilonzor", role="driver", reply_to_id=first["id"])
    assert r.json()["reply_to"]["id"] == first["id"]
    assert r.json()["reply_to"]["preview"] == "manzil qayer?"

    assert (await send(client, SENDER, "x", reply_to_id=99999)).status_code == 422
    assert (await send(client, SENDER, "   ")).status_code == 422
    r = await client.post(
        f"/chat/orders/{ORDER}/messages", json={"kind": "location", "lat": 41.3, "lon": 69.2}, headers=auth(SENDER)
    )
    assert r.status_code == 201 and r.json()["lat"] == 41.3
    r = await client.post(f"/chat/orders/{ORDER}/messages", json={"kind": "location"}, headers=auth(SENDER))
    assert r.status_code == 422


async def test_edit_and_delete_own_only(client, chat_env):
    await open_chat()
    mid = (await send(client, SENDER, "salom")).json()["id"]

    r = await client.patch(
        f"/chat/orders/{ORDER}/messages/{mid}", json={"text": "boshqa"}, headers=auth(DRIVER_USER, "driver")
    )
    assert r.status_code == 403
    r = await client.delete(f"/chat/orders/{ORDER}/messages/{mid}", headers=auth(DRIVER_USER, "driver"))
    assert r.status_code == 403

    r = await client.patch(f"/chat/orders/{ORDER}/messages/{mid}", json={"text": "salom!"}, headers=auth(SENDER))
    assert r.status_code == 200 and r.json()["text"] == "salom!" and r.json()["edited_at"]

    r = await client.delete(f"/chat/orders/{ORDER}/messages/{mid}", headers=auth(SENDER))
    assert r.status_code == 200 and r.json()["deleted_at"] and r.json()["text"] is None

    edited = [e for _, e in chat_env["broadcaster"].sent if e["type"] == "message.edited"]
    assert len(edited) == 4  # tahrir + o'chirish, har biri ikki ishtirokchiga


async def test_sync_after_id_and_changes(client):
    await open_chat()
    a = (await send(client, SENDER, "a")).json()
    sync = (await client.get(f"/chat/orders/{ORDER}/sync", params={"after_id": a["id"]}, headers=auth(SENDER))).json()
    since = sync["server_time"]

    b = (await send(client, DRIVER_USER, "b", role="driver")).json()
    await client.patch(f"/chat/orders/{ORDER}/messages/{a['id']}", json={"text": "a2"}, headers=auth(SENDER))

    r = await client.get(
        f"/chat/orders/{ORDER}/sync", params={"after_id": a["id"], "since": since}, headers=auth(SENDER)
    )
    body = r.json()
    assert [m["id"] for m in body["messages"]] == [b["id"]]
    assert [m["text"] for m in body["changed"]] == ["a2"]
    assert body["conversation"]["unread_count"] == 1


async def test_pagination_before_id(client):
    await open_chat()
    ids = [(await send(client, SENDER, str(i))).json()["id"] for i in range(5)]
    page = (await client.get(f"/chat/orders/{ORDER}/messages", params={"limit": 2}, headers=auth(SENDER))).json()
    assert [m["id"] for m in page["messages"]] == ids[3:] and page["has_more"]
    older = (
        await client.get(
            f"/chat/orders/{ORDER}/messages", params={"limit": 2, "before_id": ids[3]}, headers=auth(SENDER)
        )
    ).json()
    assert [m["id"] for m in older["messages"]] == ids[1:3]


async def test_conversations_list(client):
    await open_chat()
    await send(client, SENDER, "salom")
    lst = (await client.get("/chat/conversations", headers=auth(DRIVER_USER, "driver"))).json()
    assert len(lst) == 1 and lst[0]["unread_count"] == 1 and lst[0]["last_message"]["text"] == "salom"
    assert (await client.get("/chat/conversations", headers=auth(STRANGER))).json() == []


# --- media -----------------------------------------------------------------------


async def test_photo_upload_thumbnail_and_signed_url(client, chat_env):
    pytest.importorskip("PIL")
    await open_chat()
    files = {"file": ("IMG.jpg", jpeg_bytes(), "image/jpeg")}
    r = await client.post(f"/chat/orders/{ORDER}/media", data={"kind": "photo"}, files=files, headers=auth(SENDER))
    assert r.status_code == 201, r.text
    media = r.json()
    assert media["mime"] == "image/jpeg" and media["width"] == 800 and media["thumb_url"]

    r = await client.post(
        f"/chat/orders/{ORDER}/messages",
        json={"kind": "photo", "media_id": media["id"], "text": "yuk"},
        headers=auth(SENDER),
    )
    assert r.status_code == 201
    msg = r.json()

    # Imzolangan URL avtorizatsiyasiz ochiladi (<img src>).
    img = await client.get(msg["media"]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    thumb = await client.get(msg["media"]["thumb_url"])
    assert thumb.status_code == 200 and len(thumb.content) < len(img.content)

    # Buzilgan imzo / boshqa media.
    assert (await client.get(msg["media"]["url"].replace("sig=", "sig=0"))).status_code == 403

    # Bitta faylni ikki marta yuborib bo'lmaydi.
    r = await client.post(
        f"/chat/orders/{ORDER}/messages", json={"kind": "photo", "media_id": media["id"]}, headers=auth(SENDER)
    )
    assert r.status_code == 409

    # O'chirilganda fayl diskdan ham ketadi.
    await client.delete(f"/chat/orders/{ORDER}/messages/{msg['id']}", headers=auth(SENDER))
    assert (await client.get(msg["media"]["url"])).status_code == 404
    assert not any(p.is_file() for p in chat_env["media_root"].rglob("*"))


async def test_upload_mime_checked_from_bytes(client):
    await open_chat()
    fake = {"file": ("photo.jpg", b"<html><script>alert(1)</script></html>", "image/jpeg")}
    r = await client.post(f"/chat/orders/{ORDER}/media", data={"kind": "photo"}, files=fake, headers=auth(SENDER))
    assert r.status_code == 415

    gif = {"file": ("a.gif", b"GIF89a" + b"\x00" * 64, "image/gif")}
    r = await client.post(f"/chat/orders/{ORDER}/media", data={"kind": "photo"}, files=gif, headers=auth(SENDER))
    assert r.status_code == 415

    pdf = {"file": ("yo'l varaqasi.pdf", b"%PDF-1.4\n" + b"0" * 100, "application/octet-stream")}
    r = await client.post(f"/chat/orders/{ORDER}/media", data={"kind": "document"}, files=pdf, headers=auth(SENDER))
    assert r.status_code == 201 and r.json()["mime"] == "application/pdf" and r.json()["name"] == "yo'l varaqasi.pdf"


async def test_voice_duration_limits(client):
    await open_chat()
    m4a = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + b"\x00" * 200
    files = {"file": ("v.m4a", m4a, "audio/mp4")}
    url = f"/chat/orders/{ORDER}/media"
    assert (await client.post(url, data={"kind": "voice"}, files=files, headers=auth(SENDER))).status_code == 422
    r = await client.post(url, data={"kind": "voice", "duration_s": "301"}, files=files, headers=auth(SENDER))
    assert r.status_code == 201  # 2 s tolerantlik
    r = await client.post(url, data={"kind": "voice", "duration_s": "400"}, files=files, headers=auth(SENDER))
    assert r.status_code == 422

    media = (await client.post(url, data={"kind": "voice", "duration_s": "7.4"}, files=files, headers=auth(SENDER))).json()
    assert media["mime"] == "audio/mp4"
    r = await client.post(
        f"/chat/orders/{ORDER}/messages", json={"kind": "voice", "media_id": media["id"]}, headers=auth(SENDER)
    )
    assert r.json()["duration_s"] == 7.4
    # Tur mos kelmasa — rad.
    media2 = (await client.post(url, data={"kind": "voice", "duration_s": "3"}, files=files, headers=auth(SENDER))).json()
    r = await client.post(
        f"/chat/orders/{ORDER}/messages", json={"kind": "video", "media_id": media2["id"]}, headers=auth(SENDER)
    )
    assert r.status_code == 422


async def test_cannot_use_peers_media(client):
    await open_chat()
    pdf = {"file": ("a.pdf", b"%PDF-1.4\n" + b"0" * 10, "application/pdf")}
    media = (
        await client.post(f"/chat/orders/{ORDER}/media", data={"kind": "document"}, files=pdf, headers=auth(SENDER))
    ).json()
    r = await client.post(
        f"/chat/orders/{ORDER}/messages",
        json={"kind": "document", "media_id": media["id"]},
        headers=auth(DRIVER_USER, "driver"),
    )
    assert r.status_code == 422
