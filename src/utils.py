from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_sort_key_pair_int(pair: Tuple[int, int]) -> Tuple[int, int]:
    return pair[0], pair[1]


def canonical_sort_ints(values: Iterable[int]) -> List[int]:
    return sorted(int(v) for v in values)


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join([prefix, *parts]).encode("utf-8")
    return f"{prefix}_{sha256_bytes(raw)[:16]}"


_SPACE_RE = re.compile(r"\s+")
_NONPRINT_RE = re.compile(r"[\x00-\x1F\x7F]")


def normalize_header(text: str) -> str:
    if text is None:
        text = ""
    s = str(text)
    s = _NONPRINT_RE.sub("", s)
    s = s.strip()
    s = _SPACE_RE.sub(" ", s)
    return s


def normalize_headers(headers: Sequence[str]) -> List[str]:
    base = [normalize_header(h) for h in headers]
    seen: Dict[str, int] = {}
    out: List[str] = []
    for h in base:
        key = h
        if key == "":
            key = "col"
        if key not in seen:
            seen[key] = 0
            out.append(key)
            continue
        seen[key] += 1
        out.append(f"{key}_{seen[key]}")
    return out


def as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default