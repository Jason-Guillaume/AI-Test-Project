"""OpenAPI response-key validation shared by parser and write contracts."""

from __future__ import annotations

import re

_EXACT_CODE = re.compile(r"^[1-5][0-9]{2}$")
_RANGE_CODE = re.compile(r"^[1-5]XX$")


class InvalidResponseKey(ValueError):
    """An OpenAPI response key is outside the supported response contract."""


def normalize_response_key(value: object) -> tuple[str, int | None]:
    """Keep valid exact/range/default keys and expose an integer only for exact codes."""
    key = str(value).strip()
    if _EXACT_CODE.fullmatch(key):
        return key, int(key)
    if _RANGE_CODE.fullmatch(key) or key == "default":
        return key, None
    raise InvalidResponseKey(f"无效响应键 {key!r}；仅支持 100-599、1XX-5XX 或 default")
