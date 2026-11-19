"""Biriktirmalar: MIME baytlardan, imzolangan URL, huquq."""

from __future__ import annotations

import io
import zipfile

import pytest

from support_service import mime
from support_service.models import AttachmentKind

from .conftest import MANAGER, OWNER, STRANGER, auth, new_ticket

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


@pytest.mark.parametrize(
    "data, content_type, kind",
    [
        (PNG, "image/png", AttachmentKind.IMAGE),
        (b"\xff\xd8\xff\xe0" + b"0" * 20, "image/jpeg", AttachmentKind.IMAGE),
        (b"\x00\x00\x00\x18ftypmp42" + b"0" * 20, "video/mp4", AttachmentKind.VIDEO),
        (b"\x00\x00\x00\x14ftypqt  " + b"0" * 20, "video/quicktime", AttachmentKind.VIDEO),
        (PDF, "application/pdf", AttachmentKind.DOCUMENT),
        (_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", AttachmentKind.DOCUMENT),
    ],
)
def test_sniff_known_types(data, content_type, kind):
    sniffed = mime.sniff(data)
    assert sniffed is not None
    assert (sniffed.content_type, sniffed.kind) == (content_type, kind)


@pytest.mark.parametrize(
    "data",
    [
        b"<html><script>alert(1)</script></html>",
        b"MZ\x90\x00 executable",
        b"PK\x03\x04 not really a zip",
        b"#!/bin/sh\nrm -rf /",
    ],
)
def test_sniff_rejects_unknown(data):
    assert mime.sniff(data) is None


async def _upload(client, ticket_id, data, filename, user=OWNER, body="Mana rasm"):
    return await client.post(
        f"/support/tickets/{ticket_id}/attachments",
        files={"file": (filename, data, "image/png")},
        data={"body": body},
        headers=auth(user),
    )


async def test_upload_and_download_via_signed_url(client, actors, events):
    ticket = await new_ticket(client)
    resp = await _upload(client, ticket["id"], PNG, "../../etc/passwd.png")
    assert resp.status_code == 201, resp.text
    message = resp.json()
    att = message["attachments"][0]
    assert att["kind"] == "image"
    assert att["content_type"] == "image/png"
    assert att["filename"] == "passwd.png"
    assert message["body"] == "Mana rasm"
    assert events[-1][1]["attachments"] == 1

    # Imzolangan havola token'siz ochiladi (img teg uchun).
    file_resp = await client.get(att["url"])
    assert file_resp.status_code == 200
    assert file_resp.content == PNG
    assert file_resp.headers["content-type"] == "image/png"
    assert file_resp.headers["x-content-type-options"] == "nosniff"

    # Imzo buzilsa — 403; boshqa fayl ID si bilan ham ishlamaydi.
    tampered = att["url"].replace("sig=", "sig=0")
    assert (await client.get(tampered)).status_code in (403, 422)
    other = att["url"].replace(f"/files/{att['id']}", f"/files/{att['id'] + 1}")
    assert (await client.get(other)).status_code == 403

    # Tafsilotda ham biriktirma ko'rinadi, xodimga ham.
    detail = (await client.get(f"/support/tickets/{ticket['id']}", headers=auth(MANAGER))).json()
    assert detail["messages"][-1]["attachments"][0]["id"] == att["id"]


async def test_disguised_file_is_rejected(client, actors):
    ticket = await new_ticket(client)
    resp = await _upload(client, ticket["id"], b"<html>evil</html>", "photo.png")
    assert resp.status_code == 415


async def test_upload_to_foreign_ticket_is_404(client, actors):
    ticket = await new_ticket(client)
    resp = await _upload(client, ticket["id"], PNG, "a.png", user=STRANGER)
    assert resp.status_code == 404


async def test_upload_to_own_conversation_creates_chat(client, actors, events):
    """Birinchi xabar fayl bo'lsa ham chat yaratiladi; buyurtma raqami bog'lanadi."""
    actors.order_access[5] = {OWNER}
    resp = await client.post(
        "/support/conversation/attachments",
        files={"file": ("yuk.png", PNG, "image/png")},
        data={"body": "", "order_id": "5"},
        headers=auth(OWNER),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["attachments"][0]["kind"] == "image"
    assert data["order_id"] == 5
    assert events[-1][0] == "support.ticket_created"
    assert events[-1][1]["body"] == "📎 Biriktirma"

    conv = (await client.get("/support/conversation", headers=auth(OWNER))).json()["conversation"]
    assert conv["id"] == data["ticket_id"]


async def test_upload_to_resolved_chat_reopens_it(client, actors):
    ticket = await new_ticket(client)
    await client.patch(f"/support/tickets/{ticket['id']}/status", json={"status": "resolved"}, headers=auth(MANAGER))
    resp = await _upload(client, ticket["id"], PDF, "doc.pdf")
    assert resp.status_code == 201
    assert resp.json()["ticket"]["status"] == "open"


async def test_document_is_served_as_attachment(client, actors):
    ticket = await new_ticket(client)
    resp = await _upload(client, ticket["id"], PDF, "hisob.pdf", body="")
    assert resp.status_code == 201
    att = resp.json()["attachments"][0]
    file_resp = await client.get(att["url"])
    assert file_resp.headers["content-disposition"].startswith("attachment")
