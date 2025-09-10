# utils/ws_fallback.py
from __future__ import annotations
import os, json, time
from pathlib import Path
from typing import Optional

# HTTP גיבוי
try:
    from utils.binance_client import futures_mark_price as _mark
except Exception:
    _mark = None
try:
    from utils.binance_client import get_price as _http_price
except Exception:
    _http_price = None

_WS_CACHE_PATH = Path(os.getenv("WS_CACHE_PATH", "static/cache/ws_prices.json"))
_FRESH_TTL = int(os.getenv("PRICE_WS_FRESH_TTL", "20"))

def _read_cache() -> dict:
    try:
        if not _WS_CACHE_PATH.exists():
            return {}
        return json.loads(_WS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def is_price_fresh(symbol: str, max_age_sec: int = None) -> bool:
    """בודק אם המחיר ב-WS cache טרי מספיק."""
    max_age = _FRESH_TTL if max_age_sec is None else int(max_age_sec)
    sym = symbol.upper()
    data = _read_cache()
    rec = data.get(sym)
    if not rec:
        return False
    ts = float(rec.get("ts") or 0.0)
    return (time.time() - ts) <= max_age

def get_price(symbol: str) -> Optional[float]:
    """מחזיר מחיר אחרון: קודם Cache מ-WS (אם טרי), אחרת Mark/HTTP."""
    sym = symbol.upper()
    data = _read_cache()
    rec = data.get(sym)
    if rec:
        try:
            px = float(rec.get("price") or 0.0)
            ts = float(rec.get("ts") or 0.0)
            if px > 0 and (time.time() - ts) <= _FRESH_TTL:
                return px
        except Exception:
            pass
    # Fallback ל-HTTP
    if _mark:
        try:
            m = _mark(sym)
            if m:
                return float(m)
        except Exception:
            pass
    if _http_price:
        try:
            p = _http_price(sym)
            if p:
                return float(p)
        except Exception:
            pass
    return None































