# utils/exchange_info_cache.py
from __future__ import annotations
import os
import threading
import time
import logging
from typing import Dict, Any, Optional
from utils.binance_client import (
    futures_exchange_info_safe,
    DEFAULT_QTY_STEP_STR,
    DEFAULT_PRICE_TICK_STR,
    DEFAULT_MIN_NOTIONAL,
)

logger = logging.getLogger("algogpt.exchange_info_cache")

_lock = threading.Lock()
_cache: Dict[str, Any] = {"ts": 0.0, "symbols": {}}
# ניתן לכוון TTL מסביבת binance_client, אבל נאפשר גם כאן override
_TTL_SEC = int(os.getenv("EXCHANGE_INFO_CACHE_TTL_SEC", "900") or 900)

def preload(force: bool = False) -> None:
    """
    מושך exchangeInfo ומאכלס Cache פנימי:
    symbols[sym] = {
        pricePrecision, quantityPrecision,
        tickSizeStr, stepSizeStr, minQty, minNotional
    }
    """
    now = time.time()
    with _lock:
        if not force and (_cache["symbols"] and now - _cache["ts"] < _TTL_SEC):
            return
        data = futures_exchange_info_safe(force_refresh=force)
        if not data:
            # נשארים עם cache ישן אם יש
            if not _cache["symbols"]:
                logger.warning("exchange_info_cache.preload: no data (cold cache)")
            else:
                logger.warning("exchange_info_cache.preload: no fresh data; keeping stale cache")
            return
        out: Dict[str, Any] = {}
        for s in (data.get("symbols") or []):
            sym = (s.get("symbol") or "").upper()
            tick = DEFAULT_PRICE_TICK_STR
            step = DEFAULT_QTY_STEP_STR
            min_notional = DEFAULT_MIN_NOTIONAL
            min_qty: Optional[float] = None
            for f in (s.get("filters") or []):
                t = f.get("filterType")
                if t == "PRICE_FILTER":
                    tick = f.get("tickSize") or tick
                elif t in ("LOT_SIZE", "MARKET_LOT_SIZE", "MARKET_Lot_SIZE"):
                    step = f.get("stepSize") or step
                    if f.get("minQty") is not None:
                        try:
                            min_qty = float(f.get("minQty"))
                        except Exception:
                            pass
                elif t in ("MIN_NOTIONAL", "NOTIONAL"):
                    try:
                        min_notional = float(f.get("notional") or f.get("minNotional") or min_notional)
                    except Exception:
                        pass
            out[sym] = {
                "pricePrecision": s.get("pricePrecision", 8),
                "quantityPrecision": s.get("quantityPrecision", 8),
                "tickSizeStr": str(tick),
                "stepSizeStr": str(step),
                "minQty": min_qty,
                "minNotional": float(min_notional),
            }
        _cache["symbols"] = out
        _cache["ts"] = now

def get(symbol: str) -> Dict[str, Any]:
    """
    מחזיר את רשומת הסימבול הגולמית מה-Cache (או {} אם לא קיים).
    """
    su = (symbol or "").upper()
    preload(force=False)
    with _lock:
        return dict(_cache["symbols"].get(su, {}))

def get_filters(symbol: str) -> Dict[str, float]:
    """
    מחזיר פילטרים שימושיים בפורמט נוח:
    { "tick": float, "step": float, "minNotional": float, "minQty": Optional[float] }
    """
    rec = get(symbol)
    tick_str = rec.get("tickSizeStr", DEFAULT_PRICE_TICK_STR)
    step_str = rec.get("stepSizeStr", DEFAULT_QTY_STEP_STR)
    try:
        tick = float(tick_str)
    except Exception:
        tick = float(DEFAULT_PRICE_TICK_STR)
    try:
        step = float(step_str)
    except Exception:
        step = float(DEFAULT_QTY_STEP_STR)
    min_notional = float(rec.get("minNotional", DEFAULT_MIN_NOTIONAL))
    min_qty = rec.get("minQty")
    return {"tick": tick, "step": step, "minNotional": min_notional, "minQty": min_qty}

def get_all() -> Dict[str, Any]:
    """
    כל הטבלה של הסימבולים (עותק).
    """
    preload(force=False)
    with _lock:
        return dict(_cache["symbols"])

def info_age_sec() -> float:
    """
    גיל הנתונים בשניות (0 אם אין Cache).
    """
    preload(force=False)
    with _lock:
        ts = float(_cache.get("ts") or 0.0)
    return max(0.0, time.time() - ts) if ts else 0.0

__all__ = ["preload", "get", "get_filters", "get_all", "info_age_sec"]


