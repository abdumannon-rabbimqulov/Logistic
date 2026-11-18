"""Rasm thumbnail'i (Pillow).

Mijoz rasmni yuborishdan oldin o'zi siqadi (≈1600px JPEG), lekin lentada yuzlab
rasm bo'lishi mumkin — har biri uchun 300–600 KB yuklash sekin tarmoqda
sezilarli. Thumbnail ~20 KB, to'liq rasm faqat bosilganda ochiladi.

Video uchun server ffmpeg ishlatmaydi (image og'irlashadi): poster kadrni mijoz
`<canvas>` orqali oladi va `thumb` maydonida yuboradi — u shu yerda rasm sifatida
tekshirilib, xuddi shunday kichraytiriladi.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

try:  # Pillow bo'lmasa ham xizmat ishlayveradi — faqat thumbnail bo'lmaydi.
    from PIL import Image, ImageOps

    _HAS_PIL = True
except ImportError:  # pragma: no cover
    _HAS_PIL = False


@dataclass(frozen=True)
class Thumb:
    data: bytes
    width: int  # ASL rasm o'lchamlari (aspect-ratio uchun)
    height: int


def make_thumbnail(data: bytes, max_px: int) -> Optional[Thumb]:
    if not _HAS_PIL:
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)  # telefon rasmi yon bo'lib qolmasin
            width, height = img.size
            img.thumbnail((max_px, max_px))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=72, optimize=True)
            return Thumb(out.getvalue(), width, height)
    except Exception:
        # HEIC (Pillow'da plaginsiz ochilmaydi) yoki buzilgan fayl — thumbnail'siz.
        return None
