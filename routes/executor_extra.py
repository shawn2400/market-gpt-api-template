# routes/executor_extra.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from typing import Dict, Any, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

logger = logging.getLogger("algogpt.routes.executor_extra")

# auth: נסה utils.auth, אחרת shim זהה ל-executor.py
try:
    from utils.auth import require_api_key  # type: ignore
except Exception:
    async def require_api_key(request: Request):
        protect = (os.getenv("PROTECT_EXECUTOR_ROUTES", "1") or "").lower() in ("1", "true", "yes", "on")
        if not protect:
            return
        token = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
        if not token:
            raise HTTPException(status_code=503, detail="API_BEARER_TOKEN missing")
        auth = request.headers.get("Authorization", "") or request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        provided = auth.split(" ", 1)[1].strip()
        import hmac  # local import
        try:
            ok = hmac.compare_digest(provided, token)
        except Exception:
            ok = (provided == token)
        if not ok:
            raise HTTPException(status_code=401, detail="Unauthorized")

# binance helpers מתוך המערכת
from utils.binance_client import (  # type: ignore
    futures_mark_price,     # מחזיר float או None
    futures_balance,        # מחזיר רשימת יתרות
    get_open_positions,     # מחזיר פוזיציות פתוחות (אם יש)
)

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")


def _env_flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").lower() in ("1", "true", "yes", "on")


def _http() -> httpx.Client:
    return httpx.Client(
        http2=_env_flag("HTTP2_ENABLE", "1"),
        timeout=float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0")),
        headers={"User-Agent": "algogpt/executor-extra"},
    )


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
        # normalize: הסר פוזיציות עם כמות אפס במקרה וה־SDK מחזיר הכל
        try:
            items = [p for p in items if abs(float(p.get("positionAmt") or 0)) != 0]
        except Exception:
            pass
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as e:
        logger.exception("[executor-extra] positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance", summary="Get futures account balance")
def get_balance() -> Dict[str, Any]:
    """
    מחזיר יתרות Futures (כפי שמוחזרות ע״י utils.binance_client.futures_balance).
    """
    try:
        bal = futures_balance() or []
        return {"ok": True, "balances": bal}
    except Exception as e:
        logger.exception("[executor-extra] balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mark-price", summary="Get futures mark price")
def get_mark_price(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
) -> Dict[str, Any]:
    """
    מחזיר Mark Price של סימבול ב־Futures (Binance) דרך שכבת utils.
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=422, detail="symbol required")
    try:
        px = futures_mark_price(sym)
        if px is None:
            raise HTTPException(status_code=502, detail="mark price unavailable")
        return {"ok": True, "symbol": sym, "markPrice": float(px)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[executor-extra] mark-price error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exchange-info", summary="Raw Binance futures exchangeInfo (slim)")
def get_exchange_info() -> Dict[str, Any]:
    """
    משיכת exchangeInfo מ-Binance FAPI והחזרת גרסה "רזה" (לטובת לקוחות/דאשבורד).
    """
    url = f"{_FAPI}/fapi/v1/exchangeInfo"
    try:
        with _http() as c:
            r = c.get(url)
            r.raise_for_status()
            info = r.json()
    except Exception as e:
        logger.exception("[executor-extra] exchange-info error: %s", e)
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
        with _http() as c:
            r = c.get(url)
            r.raise_for_status()
            info = r.json()
    except Exception as e:
        logger.exception("[executor-extra] symbols error: %s", e)
        raise HTTPException(status_code=502, detail=f"get symbols failed: {e}")

    symbols = info.get("symbols", []) if isinstance(info, dict) else []
    quote = (quote or "USDT").upper().strip()
    out = sorted({
        s.get("symbol")
        for s in symbols
        if isinstance(s, dict) and _filter_usdt_perp(s, quote=quote)
    })
    return {"ok": True, "symbols": out, "count": len(out)}



