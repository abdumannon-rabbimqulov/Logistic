"""Media saqlash qatlami.

`Storage` — interfeys. Hozir bitta amalga oshirish: `LocalStorage` (compose'dagi
`uploads/chat` volume'i). Keyin S3/MinIO kerak bo'lsa shu protokolni bajaruvchi
klass qo'shiladi; router va iste'molchi o'zgarmaydi. Kalit (`key`) — nisbiy yo'l,
`<conversation_id>/<media_id>.<ext>`; absolyut yo'l hech qachon DB'ga yozilmaydi.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional, Protocol

from chat_service.config import MEDIA_ROOT


class Storage(Protocol):
    async def save(self, key: str, data: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...

    def local_path(self, key: str) -> Optional[Path]:
        """Fayl diskda bo'lsa — yo'li (FileResponse uchun, Range qo'llab-quvvatlanadi)."""
        ...


class LocalStorage:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Kalit tashqaridan kelmaydi, lekin baribir: `..` bilan ildizdan chiqib bo'lmasin.
        if self.root not in path.parents:
            raise ValueError(f"Yaroqsiz saqlash kaliti: {key!r}")
        return path

    async def save(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)  # yarim yozilgan fayl hech qachon ko'rinmasin

        await asyncio.to_thread(_write)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))

    def local_path(self, key: str) -> Optional[Path]:
        path = self._path(key)
        return path if path.is_file() else None


_storage: Optional[Storage] = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(MEDIA_ROOT)
    return _storage


def set_storage(storage: Storage) -> None:
    """Testlar uchun (vaqtinchalik papka)."""
    global _storage
    _storage = storage
