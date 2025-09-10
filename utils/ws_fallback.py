# utils/ws_fallback.py
from __future__ import annotations
import os, json, time
from pathlib import Path
from typing import Optional, Dict, Any

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

def _read_cache() -> Dict[str, Any]:
    try:
        if not _WS_CACHE_PATH.exists():
            return {}
        return json.loads(_WS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def is_price_fresh(symbol: str, max_age_sec: int | None = None) -> bool:
    """בודק אם המחיר ב-WS cache טרי מספיק עבור הסימבול הנתון."""
    max_age = _FRESH_TTL if max_age_sec is None else int(max_age_sec)
    sym = symbol.upper()
    data = _read_cache()
    rec = data.get(sym)
    if not rec:
        return False
    try:
        ts = float(rec.get("ts") or 0.0)
    except Exception:
        return False
    return (time.time() - ts) <= max_age

def get_last_ts(symbol: str) -> float:
    """
    מחזיר את חותמת הזמן (epoch seconds) של המחיר האחרון מה־WS cache.
    אם אין, מחזיר 0.0.
    """
    sym = symbol.upper()
    data = _read_cache()
    rec = data.get(sym)
    if not rec:
        return 0.0
    try:
        ts = float(rec.get("ts") or 0.0)
        return ts if ts > 0 else 0.0
    except Exception:
        return 0.0

def get_price_age(symbol: str) -> Optional[float]:
    """
    מחזיר גיל המחיר ב־שניות (כמה זמן עבר מאז העדכון האחרון), או None אם אין נתון.
    """
    ts = get_last_ts(symbol)
    if ts <= 0:
        return None
    return max(0.0, time.time() - ts)

def get_price(symbol: str) -> Optional[float]:
    """
    מחזיר מחיר אחרון: קודם Cache מ-WS (אם טרי), אחרת Mark/HTTP. אם הכל נכשל — None.
    """
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
    # Fallback ל-HTTP (Mark ולאחר מכן מחיר רגיל)
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

__all__ = ["is_price_fresh", "get_price", "get_last_ts", "get_price_age"]































