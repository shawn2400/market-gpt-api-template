# routes/price.py
from __future__ import annotations

import asyncio
import time
import logging
import os
from typing import Optional, Dict, Any

from fastapi import APIRouter, Path, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

# ws_fallback (optional)
try:
    from utils.ws_fallback import get_price as get_cached_price, update_price
except Exception:
    def get_cached_price(symbol: str) -> Optional[float]:  # type: ignore
        return None
    def update_price(symbol: str, price: float) -> None:  # type: ignore
        return None

# sync futures_mark_price (optional)
try:
    from utils.binance_client import futures_mark_price, futures_index_price  # type: ignore
except Exception:
    def futures_mark_price(symbol: str) -> Optional[float]:  # type: ignore
        return None
    def futures_index_price(symbol: str) -> Optional[float]:  # type: ignore
        return None

LOG = logging.getLogger("algogpt.price")
router = APIRouter(prefix="/price", tags=["price"])

CACHE_TTL = float(os.getenv("PRICE_API_CACHE_TTL", "0.5"))  # seconds
_last: Dict[str, Dict[str, Any]] = {}  # sym -> {"ts": float, "val": float}

def _now() -> float:
    return time.time()

def _cache_get(sym: str) -> Optional[float]:
    rec = _last.get(sym.upper())
    if not rec:
        return None
    if (_now() - rec.get("ts", 0.0)) <= CACHE_TTL:
        return float(rec.get("val"))
    return None

def _cache_put(sym: str, val: float) -> None:
    _last[sym.upper()] = {"ts": _now(), "val": float(val)}

def _best_price(sym: str) -> Optional[float]:
    # 1) fresh WS
    try:
        v = get_cached_price(sym)
        if v is not None:
            return float(v)
    except Exception:
        pass
    # 2) mark price REST
    try:
        v = futures_mark_price(sym)
        if v is not None:
            # feed WS fallback cache (best effort)
            try:
                update_price(sym, float(v))
            except Exception:
                pass
            return float(v)
    except Exception:
        pass
    # 3) index price as last resort
    try:
        v = futures_index_price(sym)
        if v is not None:
            try:
                update_price(sym, float(v))
            except Exception:
                pass
            return float(v)
    except Exception:
        pass
    return None

@router.get("/{symbol}", response_class=JSONResponse, summary="Latest price (coalesced WS/REST)")
def price_one(symbol: str = Path(..., description="e.g. BTCUSDT"),
              source: Optional[str] = Query(None, description="force source: ws|mark|index")):
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol required")

    # tiny local cache
    v = _cache_get(sym)
    if v is None:
        if (source or "").lower() == "ws":
            v = get_cached_price(sym)
        elif (source or "").lower() == "mark":
            v = futures_mark_price(sym)
        elif (source or "").lower() == "index":
            v = futures_index_price(sym)
        else:
            v = _best_price(sym)
        if v is None:
            raise HTTPException(status_code=503, detail="price_unavailable")
        _cache_put(sym, float(v))

    return {"ok": True, "symbol": sym, "price": float(v)}

@router.get("/{symbol}/plain", response_class=PlainTextResponse, summary="Plain price for quick probes")
def price_plain(symbol: str = Path(..., description="e.g. BTCUSDT")):
    sym = symbol.strip().upper()
    v = _cache_get(sym) or _best_price(sym)
    if v is None:
        raise HTTPException(status_code=503, detail="price_unavailable")
    return f"{v:.8f}"





