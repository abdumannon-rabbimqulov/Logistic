"""Fayl turini BAYTLARDAN aniqlash (magic number).

Mijoz yuborgan `Content-Type` va fayl kengaytmasiga ishonilmaydi: `rasm.jpg` deb
nomlangan HTML yoki skript ham yuklanishi mumkin. Faqat quyidagi ro'yxatdagi
formatlar qabul qilinadi; qolgani 415 bilan rad etiladi. Tashqi kutubxona
(libmagic) ataylab ishlatilmaydi — image'ga tizim kutubxonasi qo'shmaslik uchun.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Optional

from support_service.models import AttachmentKind


@dataclass(frozen=True)
class Sniffed:
    content_type: str
    kind: AttachmentKind
    ext: str


_IMAGE = AttachmentKind.IMAGE
_VIDEO = AttachmentKind.VIDEO
_DOC = AttachmentKind.DOCUMENT

# ISO-BMFF (`....ftyp<brand>`) brendlari.
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
_MP4_BRANDS = {b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash", b"M4V ", b"MSNV"}
_MOV_BRANDS = {b"qt  "}
_3GP_PREFIX = (b"3gp", b"3g2")


def _sniff_zip_office(data: bytes) -> Optional[Sniffed]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, ValueError):
        return None
    if "[Content_Types].xml" not in names:
        return None
    if any(n.startswith("word/") for n in names):
        return Sniffed(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _DOC, ".docx"
        )
    if any(n.startswith("xl/") for n in names):
        return Sniffed("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _DOC, ".xlsx")
    if any(n.startswith("ppt/") for n in names):
        return Sniffed(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation", _DOC, ".pptx"
        )
    return None


def sniff(data: bytes) -> Optional[Sniffed]:
    """Qo'llab-quvvatlanadigan tur bo'lsa `Sniffed`, aks holda `None`."""
    head = data[:64]
    if head.startswith(b"\xff\xd8\xff"):
        return Sniffed("image/jpeg", _IMAGE, ".jpg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Sniffed("image/png", _IMAGE, ".png")
    if head.startswith((b"GIF87a", b"GIF89a")):
        return Sniffed("image/gif", _IMAGE, ".gif")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Sniffed("image/webp", _IMAGE, ".webp")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIF_BRANDS:
            return Sniffed("image/heic", _IMAGE, ".heic")
        if brand in _MOV_BRANDS:
            return Sniffed("video/quicktime", _VIDEO, ".mov")
        if brand in _MP4_BRANDS:
            return Sniffed("video/mp4", _VIDEO, ".mp4")
        if brand.startswith(_3GP_PREFIX):
            return Sniffed("video/3gpp", _VIDEO, ".3gp")
        return None
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return Sniffed("video/webm", _VIDEO, ".webm")
    if head.startswith(b"%PDF-"):
        return Sniffed("application/pdf", _DOC, ".pdf")
    if head.startswith(b"PK\x03\x04"):
        return _sniff_zip_office(data)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # Eski MS Office (doc/xls) — OLE konteyner; ichki turini ajratmaymiz.
        return Sniffed("application/msword", _DOC, ".doc")
    return None
