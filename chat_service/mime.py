"""Fayl turini BAYTLARDAN aniqlash (mijoz yuborgan `Content-Type` ga ishonilmaydi).

Nega kutubxonasiz (python-magic/libmagic): bizga faqat o'nga yaqin format kerak,
libmagic esa image'ga tizim kutubxonasini qo'shadi va Go'ga ko'chirishda
`http.DetectContentType` + shu jadval kifoya. Imzolar: magic-number'lar
(JPEG FF D8 FF, PNG 89 50 4E 47, ISO-BMFF `ftyp`, EBML 1A 45 DF A3, ...).
"""

from __future__ import annotations

from typing import Optional

from chat_service.domain import KIND_DOCUMENT, KIND_PHOTO, KIND_VIDEO, KIND_VOICE

# ISO-BMFF (`....ftyp<brand>`) brendlari: audio-only va video konteynerlarni ajratish.
_AUDIO_MP4_BRANDS = {b"M4A ", b"M4B ", b"F4A "}
_QUICKTIME_BRANDS = {b"qt  "}
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
_3GP_PREFIX = b"3g"


def sniff_mime(head: bytes) -> Optional[str]:
    """Fayl boshidagi baytlardan MIME. Taniqsiz bo'lsa `None`.

    Kamida ~16 bayt berilishi kerak (WEBP uchun 12, ftyp uchun 12).
    """
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        # WebM/Matroska: audio yoki video ekanini konteyner sarlavhasidan bilib
        # bo'lmaydi (treklarni parse qilish kerak). Kontekstni `kind` hal qiladi.
        return "video/webm"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xF6) == 0xF0:
        return "audio/aac"  # ADTS
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIF_BRANDS:
            return "image/heic"
        if brand in _AUDIO_MP4_BRANDS:
            return "audio/mp4"
        if brand in _QUICKTIME_BRANDS:
            return "video/quicktime"
        if brand.startswith(_3GP_PREFIX):
            return "video/3gpp"
        return "video/mp4"
    return None


# Har tur uchun qabul qilinadigan MIME'lar. GIF ATAYLAB yo'q (talab: GIF kerak emas).
ALLOWED: dict[str, frozenset[str]] = {
    KIND_PHOTO: frozenset({"image/jpeg", "image/png", "image/webp", "image/heic"}),
    KIND_VIDEO: frozenset({"video/mp4", "video/quicktime", "video/webm", "video/3gpp"}),
    # iOS MediaRecorder — audio/mp4 (AAC), Android Chrome — audio/webm (Opus).
    # MP4 konteynerda yozilgan ovoz ba'zan `isom`/`mp42` brendi bilan keladi —
    # u `video/mp4` deb aniqlanadi, shuning uchun ovoz uchun ham ruxsat.
    KIND_VOICE: frozenset(
        {"audio/mp4", "video/mp4", "video/webm", "audio/ogg", "audio/aac", "audio/mpeg"}
    ),
    KIND_DOCUMENT: frozenset({"application/pdf"}),
}

# Ovoz uchun konteyner MIME'ini audio ko'rinishiga keltirish (brauzer <audio> uchun).
_VOICE_NORMALIZE = {"video/webm": "audio/webm", "video/mp4": "audio/mp4"}

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/3gpp": "3gp",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/aac": "aac",
    "audio/mpeg": "mp3",
    "application/pdf": "pdf",
}


class MimeRejected(ValueError):
    pass


def resolve_mime(kind: str, head: bytes) -> str:
    """`kind` uchun fayl baytlari mos kelsa — saqlanadigan MIME, aks holda istisno."""
    detected = sniff_mime(head)
    if detected is None:
        raise MimeRejected("Fayl turi aniqlanmadi yoki qo'llab-quvvatlanmaydi")
    allowed = ALLOWED.get(kind)
    if allowed is None:
        raise MimeRejected(f"Noma'lum media turi: {kind}")
    if detected not in allowed:
        raise MimeRejected(f"'{kind}' uchun bu fayl turi mos emas ({detected})")
    if kind == KIND_VOICE:
        return _VOICE_NORMALIZE.get(detected, detected)
    return detected
