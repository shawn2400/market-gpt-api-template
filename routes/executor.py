# routes/executor.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
from typing import Dict, Any, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

# ---- soft auth shim (אם utils.auth לא קיים) ----
try:
    from utils.auth import require_api_key  # type: ignore
except Exception:
    async def require_api_key(request: Request):
        protect = os.getenv("PROTECT_EXECUTOR_ROUTES", "1").lower() in ("1", "true", "yes", "on")
        if not protect:
            return
        token = (os.getenv("API_BEARER_TOKEN") or os.getenv("API_TOKEN") or "").strip()
        if not token:
            raise HTTPException(status_code=503, detail="API_BEARER_TOKEN missing")
        auth = request.headers.get("Authorization", "")
        if not (auth.startswith("Bearer ") and auth.split(" ", 1)[1].strip() == token):
            raise HTTPException(status_code=401, detail="Unauthorized")

logger = logging.getLogger("algogpt.routes.executor")

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")


def _filter_usdt_perp(sym: Dict[str, Any], quote: str = "USDT") -> bool:
    try:
        if sym.get("status") != "TRADING":
            return False
        if sym.get("quoteAsset") != quote:
            return False
        ct = (sym.get("contractType") or "").upper()
        return ct in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER")
    except Exception:
        return False


def _http() -> httpx.Client:
    # חיבור קל עם timeout סביר
    return httpx.Client(timeout=10.0, headers={"User-Agent": "algogpt/executor"})


@router.get("/positions", summary="List open futures positions")
def list_positions() -> Dict[str, Any]:
    """
    מחזיר פוזיציות פתוחות ע״י SDK אם קיים; אחרת 501.
    """
    try:
        from binance.client import Client  # type: ignore
        cli = Client(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", ""), testnet=os.getenv("BINANCE_TESTNET", "0") in ("1","true","on"))
        items = cli.futures_position_information() or []
        # סינון רק פוזיציות עם כמות != 0
        items = [p for p in items if abs(float(p.get("positionAmt") or 0)) > 0]
        return {"ok": True, "items": items, "count": len(items)}
    except ImportError:
        raise HTTPException(status_code=501, detail="python-binance not installed")
    except Exception as e:
        logger.exception("[executor] positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance", summary="Get futures account balance")
def get_balance() -> Dict[str, Any]:
    try:
        from binance.client import Client  # type: ignore
        cli = Client(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", ""), testnet=os.getenv("BINANCE_TESTNET", "0") in ("1","true","on"))
        bal = cli.futures_account_balance()
        return {"ok": True, "balances": bal}
    except ImportError:
        raise HTTPException(status_code=501, detail="python-binance not installed")
    except Exception as e:
        logger.exception("[executor] balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mark-price", summary="Get futures mark price")
def get_mark_price(symbol: str = Query(..., description="e.g. BTCUSDT")) -> Dict[str, Any]:
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=422, detail="symbol required")
    url = f"{_FAPI}/fapi/v1/premiumIndex"
    try:
        with _http() as c:
            r = c.get(url, params={"symbol": sym})
            r.raise_for_status()
            data = r.json()
            # premiumIndex מחזיר markPrice
            mp = float(data.get("markPrice"))
            return {"ok": True, "symbol": sym, "markPrice": mp}
    except Exception as e:
        logger.exception("[executor] mark-price error: %s", e)
        raise HTTPException(status_code=502, detail="mark price unavailable")


@router.get("/exchange-info", summary="Raw Binance futures exchangeInfo (slim)")
def get_exchange_info() -> Dict[str, Any]:
    url = f"{_FAPI}/fapi/v1/exchangeInfo"
    try:
        with _http() as c:
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
                "filters": [
                    f for f in (s.get("filters") or [])
                    if f.get("filterType") in {"PRICE_FILTER", "LOT_SIZE"}
                ],
            })
        except Exception:
            continue
    return {"ok": True, "symbols": slim, "count": len(slim)}


@router.get("/symbols", summary="Tradable USDT-M futures symbols")
def get_symbols(quote: str = Query("USDT", description="סימול מטבע ציטוט (ברירת מחדל USDT)")) -> Dict[str, Any]:
    url = f"{_FAPI}/fapi/v1/exchangeInfo"
    try:
        with _http() as c:
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







