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

def _from_cache(symbol: str) -> Optional[float]:
    try:
        if not _WS_CACHE_PATH.exists():
            return None
        data = json.loads(_WS_CACHE_PATH.read_text(encoding="utf-8"))
        rec = data.get(symbol.upper())
        if not rec:
            return None
        px = float(rec.get("price") or 0.0)
        ts = float(rec.get("ts") or 0.0)
        if px > 0 and (time.time() - ts) <= _FRESH_TTL:
            return px
    except Exception:
        return None
    return None

def get_price(symbol: str) -> Optional[float]:
    """מחזיר מחיר אחרון: קודם Cache מ-WS (אם טרי), אחרת Mark/HTTP."""
    symbol = symbol.upper()
    px = _from_cache(symbol)
    if px:
        return px
    # Fallback ל-HTTP
    if _mark:
        try:
            m = _mark(symbol)
            if m:
                return float(m)
        except Exception:
            pass
    if _http_price:
        try:
            p = _http_price(symbol)
            if p:
                return float(p)
        except Exception:
            pass
    return None






























