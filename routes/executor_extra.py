# routes/executor_extra.py
from __future__ import annotations
import logging, os
from typing import Dict, Any, List
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_api_key
from utils.binance_client import (
    futures_mark_price,     # קיימים במערכת
    futures_balance,        # מחזיר רשימת יתרות
    get_open_positions,     # מחזיר פוזיציות פתוחות (אם יש)
)

logger = logging.getLogger("algogpt.routes.executor_extra")

# שמרנו את שם המודול/קובץ, אבל מיישרים prefix ל-/executor כדי להתאים למערכת והבדיקות
router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")


def _filter_usdt_perp(sym: Dict[str, Any], quote: str = "USDT") -> bool:
    """
    סינון סימבולים רלוונטיים למסחר USDT-M (PERPETUAL/Quarterly) במצב TRADING.
    """
    try:
        if sym.get("status") != "TRADING":
            return False
        if sym.get("quoteAsset") != quote:
            return False
        ct = (sym.get("contractType") or "").upper()
        return ct in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER")
    except Exception:
        return False


@router.get("/positions", summary="List open futures positions")
def list_positions() -> Dict[str, Any]:
    """
    מחזיר את כל הפוזיציות הפתוחות (אם יש).
    """
    try:
        items = get_open_positions() or []
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as e:
        logger.exception("[executor] positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance", summary="Get futures account balance")
def get_balance() -> Dict[str, Any]:
    """
    מחזיר יתרות Futures (כפי שמוחזרות ע״י utils.binance_client.futures_balance).
    """
    try:
        bal = futures_balance()
        return {"ok": True, "balances": bal}
    except Exception as e:
        logger.exception("[executor] balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mark-price", summary="Get futures mark price")
def get_mark_price(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
) -> Dict[str, Any]:
    """
    מחזיר Mark Price של סימבול ב־Futures (Binance).
    """
    try:
        sym = (symbol or "").upper().strip()
        px = futures_mark_price(sym)
        if not px:
            raise HTTPException(status_code=502, detail="mark price unavailable")
        return {"ok": True, "symbol": sym, "markPrice": float(px)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[executor] mark-price error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exchange-info", summary="Raw Binance futures exchangeInfo (slim)")
def get_exchange_info() -> Dict[str, Any]:
    """
    משיכת exchangeInfo מ-Binance FAPI והחזרת גרסה "רזה" (לטובת לקוחות/דאשבורד).
    """
    url = f"{_FAPI}/fapi/v1/exchangeInfo"
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(url)
            r.raise_for_status()
            info = r.json()
    except Exception as e:
        logger.exception("[executor] exchange-info error: %s", e)
        raise HTTPException(status_code=502, detail=f"exchangeInfo failed: {e}")

    symbols = info.get("symbols", []) if isinstance(info, dict) else []
    slim: List[Dict[str, Any]] = []
    for s in symbols:
        try:
            slim.append({
                "symbol": s.get("symbol"),
                "baseAsset": s.get("baseAsset"),
                "quoteAsset": s.get("quoteAsset"),
                "contractType": s.get("contractType"),
                "status": s.get("status"),
                # משאירים רק פילטרים חיוניים
                "filters": [
                    f for f in (s.get("filters") or [])
                    if f.get("filterType") in {"PRICE_FILTER", "LOT_SIZE"}
                ],
            })
        except Exception:
            continue
    return {"ok": True, "symbols": slim, "count": len(slim)}


@router.get("/symbols", summary="Tradable USDT-M futures symbols")
def get_symbols(
    quote: str = Query("USDT", description="סימול מטבע ציטוט (ברירת מחדל USDT)"),
) -> Dict[str, Any]:
    """
    מחזיר רשימת סימבולים סחירים ל-USDT-M (PERPETUAL/Quarterly) במצב TRADING.
    """
    url = f"{_FAPI}/fapi/v1/exchangeInfo"
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(url)
            r.raise_for_status()
            info = r.json()
    except Exception as e:
        logger.exception("[executor] symbols error: %s", e)
        raise HTTPException(status_code=502, detail=f"get symbols failed: {e}")

    symbols = info.get("symbols", []) if isinstance(info, dict) else []
    quote = (quote or "USDT").upper().strip()
    out = sorted({
        s.get("symbol")
        for s in symbols
        if isinstance(s, dict) and _filter_usdt_perp(s, quote=quote)
    })
    return {"ok": True, "symbols": out, "count": len(out)}








