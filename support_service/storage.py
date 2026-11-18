"""Fayl ombori interfeysi va imzolangan URL'lar.

Interfeys ataylab support'ga bog'lanmagan (faqat `key` → bayt): keyinchalik
sender↔haydovchi chati ham shu qatlamni ishlatishi, yoki lokal disk o'rniga S3
qo'yilishi uchun faqat yangi `Storage` amalga oshirmasi kerak bo'ladi.

Imzolangan URL: `<resource>?exp=<unix>&sig=<hmac>`. `<img>`/`<video>` teglari
`Authorization` sarlavhasini yubora olmaydi, shuning uchun fayl bearer token bilan
emas, qisqa muddatli imzo bilan beriladi. Imzo kaliti `SECRET_KEY` dan ALOHIDA
maqsad uchun hosil qilinadi (domain separation) — JWT bilan aralashmasin.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from support_service.config import SECRET_KEY, SIGNED_URL_TTL_SECONDS, UPLOAD_DIR


class Storage(Protocol):
    async def save(self, key: str, data: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...

    def local_path(self, key: str) -> Optional[Path]:
        """Lokal fayl yo'li (FileResponse uchun). Masofaviy omborda `None`."""
        ...


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Kalitlar biz tomonda yasaladi, lekin baribir ildizdan chiqib ketmasin.
        if self.root not in path.parents:
            raise ValueError("Yaroqsiz ombor kaliti")
        return path

    async def save(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)

        await asyncio.to_thread(_write)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))

    def local_path(self, key: str) -> Optional[Path]:
        path = self._path(key)
        return path if path.is_file() else None


def new_key(prefix: str, ext: str) -> str:
    now = datetime.now(timezone.utc)
    return f"{prefix}/{now:%Y/%m}/{uuid.uuid4().hex}{ext}"


_storage: Optional[Storage] = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(UPLOAD_DIR)
    return _storage


def set_storage(storage: Optional[Storage]) -> None:
    global _storage
    _storage = storage


_SIGNING_KEY = hmac.new(SECRET_KEY.encode(), b"support-file-url-v1", hashlib.sha256).digest()


def _signature(resource: str, exp: int) -> str:
    msg = f"{resource}\n{exp}".encode()
    return hmac.new(_SIGNING_KEY, msg, hashlib.sha256).hexdigest()[:32]


def sign_url(resource: str, ttl: int = SIGNED_URL_TTL_SECONDS) -> str:
    # Muddat soat boshiga yaxlitlanadi: bir xil fayl uchun URL bir soat davomida
    # o'zgarmaydi va brauzer keshi ishlaydi.
    exp = (int(time.time()) // 3600 + 1) * 3600 + ttl
    return f"{resource}?exp={exp}&sig={_signature(resource, exp)}"


def verify_signature(resource: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(_signature(resource, exp), sig)
