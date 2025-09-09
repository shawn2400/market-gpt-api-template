# routes/binance_status.py
from __future__ import annotations
import logging
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import futures_mark_price, fapi_ping, futures_exchange_info_safe

logger = logging.getLogger("algogpt.routes.binance_status")

router = APIRouter(
    prefix="/binance",
    tags=["Binance"],
    dependencies=[Depends(require_api_key)],
)

@router.get("/ping")
def ping() -> Dict[str, Any]:
    """בודק זמינות Binance API (fapi)."""
    try:
        return {"ok": bool(fapi_ping())}
    except Exception as e:
        logger.warning("binance/ping failed: %s", e)
        return {"ok": False}

@router.get("/status")
def binance_status(symbols: str = Query("BTCUSDT,ETHUSDT,BNBUSDT")) -> Dict[str, Any]:
    """
    סטטוס כללי: ping + דגימת Mark Price למספר סימבולים.
    אפשר להעביר ?symbols=BTCUSDT,SOLUSDT,ADAUSDT
    """
    syms: List[str] = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    samples: Dict[str, Any] = {}
    try:
        ping_ok = bool(fapi_ping())
    except Exception as e:
        logger.warning("fapi_ping failed: %s", e)
        ping_ok = False

    for sym in syms:
        try:
            samples[sym] = futures_mark_price(sym)
        except Exception as e:
            logger.warning("mark_price failed for %s: %s", sym, e)
            samples[sym] = None

    return {"ok": ping_ok, "ping_ok": ping_ok, "samples": samples}

@router.get("/mark-price")
def mark_price(symbol: str = Query(..., min_length=6, max_length=20)) -> Dict[str, Any]:
    """מחזיר Mark Price לסימבול יחיד."""
    try:
        price = futures_mark_price(symbol)
        if price is None:
            raise HTTPException(status_code=503, detail="mark price unavailable")
        return {"ok": True, "symbol": symbol.upper(), "markPrice": price}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("binance/mark-price failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch mark price: {e}")

@router.get("/exchange-info")
def exchange_info(force_refresh: int = Query(0, ge=0, le=1)) -> Dict[str, Any]:
    """מחזיר snapshot של exchangeInfo (Binance Futures). force_refresh=1 כדי לרענן מטמון פנימי, אם קיים."""
    try:
        data = futures_exchange_info_safe(force_refresh=bool(force_refresh))
        if not data or "symbols" not in data:
            raise HTTPException(status_code=502, detail="Exchange info unavailable")
        return {"ok": True, "symbols": data.get("symbols"), "rateLimits": data.get("rateLimits")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("binance/exchange-info failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch exchange info: {e}")

















