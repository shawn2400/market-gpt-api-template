# utils/pagination.py
from __future__ import annotations
from typing import Iterable, List, Dict, Any, Tuple

MAX_LIMIT_CAP = 200

def clamp_int(v: int, min_v: int, max_v: int) -> int:
    return max(min_v, min(max_v, v))

def paginate_list(items: List[Any], limit: int, offset: int) -> Tuple[List[Any], int]:
    total = len(items)
    limit = clamp_int(limit, 1, MAX_LIMIT_CAP)
    offset = max(0, offset)
    return items[offset: offset + limit], total

def filter_fields(obj: Dict[str, Any], fields: List[str] | None) -> Dict[str, Any]:
    if not fields:
        return obj
    out = {}
    for f in fields:
        if f in obj:
            out[f] = obj[f]
    return out

def parse_fields_param(s: str | None) -> List[str] | None:
    if not s:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]
