"""Fayl turi baytlardan aniqlanadi — mijoz yuborgan nom/Content-Type'ga ishonilmaydi."""

from __future__ import annotations

import pytest

from chat_service.mime import MimeRejected, resolve_mime, sniff_mime

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 16
PDF = b"%PDF-1.7\n" + b"\x00" * 16
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 16
M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + b"\x00" * 8
MP4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00" + b"\x00" * 8
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00" + b"\x00" * 8
EXE = b"MZ\x90\x00" + b"\x00" * 20
HTML = b"<!DOCTYPE html><script>alert(1)</script>"


@pytest.mark.parametrize(
    "head,expected",
    [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
        (GIF, "image/gif"),
        (PDF, "application/pdf"),
        (WEBM, "video/webm"),
        (M4A, "audio/mp4"),
        (MP4, "video/mp4"),
        (MOV, "video/quicktime"),
        (EXE, None),
        (HTML, None),
    ],
)
def test_sniff(head, expected):
    assert sniff_mime(head) == expected


@pytest.mark.parametrize(
    "kind,head,mime",
    [
        ("photo", JPEG, "image/jpeg"),
        ("photo", PNG, "image/png"),
        ("video", MP4, "video/mp4"),
        ("video", MOV, "video/quicktime"),
        ("video", WEBM, "video/webm"),
        # iOS: audio/mp4 (AAC); Android: webm/opus — ikkalasi audio ko'rinishiga keltiriladi.
        ("voice", M4A, "audio/mp4"),
        ("voice", MP4, "audio/mp4"),
        ("voice", WEBM, "audio/webm"),
        ("document", PDF, "application/pdf"),
    ],
)
def test_allowed(kind, head, mime):
    assert resolve_mime(kind, head) == mime


@pytest.mark.parametrize(
    "kind,head",
    [
        ("photo", GIF),  # GIF talab bo'yicha kerak emas
        ("photo", PDF),
        ("photo", HTML),  # .jpg deb nomlangan HTML — XSS urinish
        ("document", JPEG),  # hujjat faqat PDF
        ("document", EXE),
        ("video", PDF),
        ("voice", JPEG),
        ("sticker", PNG),
    ],
)
def test_rejected(kind, head):
    with pytest.raises(MimeRejected):
        resolve_mime(kind, head)
