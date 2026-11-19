"""JSON Schema'ning kichik qismi bo'yicha tekshiruv (tashqi kutubxonasiz).

Qo'llab-quvvatlanadi: `type` (yoki turlar ro'yxati), `required`, `properties`,
`items`, `enum`. Event payload'lari uchun shu yetarli.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMAS_DIR = Path(__file__).parent / "schemas"

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


@lru_cache(maxsize=None)
def load_schema(event: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / f"{event}.json").read_text(encoding="utf-8"))


def _type_ok(value: Any, expected: Any) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    for name in names:
        py = _TYPES[name]
        # bool — int'ning pastki turi; "integer" ga bool kirmasin.
        if name in ("integer", "number") and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


def errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    out: list[str] = []
    if "type" in schema and not _type_ok(value, schema["type"]):
        return [f"{path}: kutilgan tur {schema['type']}, keldi {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {value!r} ruxsat etilgan qiymatlardan emas")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path}: majburiy '{key}' yo'q")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                out.extend(errors(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            out.extend(errors(item, schema["items"], f"{path}[{i}]"))
    return out


def validate_payload(event: str, payload: dict[str, Any]) -> list[str]:
    """Bo'sh ro'yxat — payload sxemaga mos."""
    return errors(payload, load_schema(event))
