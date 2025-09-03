# utils/exchange_info_cache.py
from __future__ import annotations
import threading, time
from typing import Dict, Any, Optional
from utils.binance_client import futures_exchange_info_safe, DEFAULT_QTY_STEP_STR, DEFAULT_PRICE_TICK_STR, DEFAULT_MIN_NOTIONAL

_lock = threading.Lock()
_cache: Dict[str, Any] = {"ts": 0.0, "symbols": {}}
_TTL_SEC = 900

def preload(force: bool = False) -> None:
    now = time.time()
    with _lock:
        if not force and (_cache["symbols"] and now - _cache["ts"] < _TTL_SEC):
            return
        data = futures_exchange_info_safe(force_refresh=force)
        out: Dict[str, Any] = {}
        for s in (data.get("symbols") or []):
            sym = (s.get("symbol") or "").upper()
            tick = DEFAULT_PRICE_TICK_STR
            step = DEFAULT_QTY_STEP_STR
            min_notional = DEFAULT_MIN_NOTIONAL
            min_qty = None
            for f in (s.get("filters") or []):
                t = f.get("filterType")
                if t == "PRICE_FILTER":
                    tick = f.get("tickSize") or tick
                elif t in ("LOT_SIZE","MARKET_LOT_SIZE"):
                    step = f.get("stepSize") or step
                    if f.get("minQty") is not None:
                        try: min_qty = float(f.get("minQty"))
                        except Exception: pass
                elif t in ("MIN_NOTIONAL","NOTIONAL"):
                    try: min_notional = float(f.get("notional") or f.get("minNotional") or min_notional)
                    except Exception: pass
            out[sym] = {
                "pricePrecision": s.get("pricePrecision", 8),
                "quantityPrecision": s.get("quantityPrecision", 8),
                "tickSizeStr": str(tick), "stepSizeStr": str(step),
                "minQty": min_qty, "minNotional": float(min_notional),
            }
        _cache["symbols"] = out
        _cache["ts"] = now

def get(symbol: str) -> Dict[str, Any]:
    su = (symbol or "").upper()
    preload(force=False)
    with _lock:
        return dict(_cache["symbols"].get(su) or {
            "pricePrecision": 8, "quantityPrecision": 8,
            "tickSizeStr": str(DEFAULT_PRICE_TICK_STR),
            "stepSizeStr": str(DEFAULT_QTY_STEP_STR),
            "minQty": None, "minNotional": float(DEFAULT_MIN_NOTIONAL),
        })

