# routes/executor.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import hmac
from typing import Dict, Any, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

logger = logging.getLogger("algogpt.routes.executor")

# ---------- Auth (utils.auth או shim זהה) ----------
try:
    from utils.auth import require_api_key  # type: ignore
except Exception:
    async def require_api_key(request: Request):
        """
        הגנה בסיסית עם Bearer Token אם PROTECT_EXECUTOR_ROUTES=1.
        """
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
        try:
            ok = hmac.compare_digest(provided, token)
        except Exception:
            ok = (provided == token)
        if not ok:
            raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter(
    prefix="/executor",
    tags=["Executor"],
    dependencies=[Depends(require_api_key)],
)

# ---------- ENV helpers ----------
def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").lower() in ("1", "true", "yes", "on")

HTTP2_ENABLE = _flag("HTTP2_ENABLE", "1")
BINANCE_HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0"))
FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")
EXECUTOR_USE_UTILS = _flag("EXECUTOR_USE_UTILS", "1")
EXECUTOR_ALLOW_FALLBACK = _flag("EXECUTOR_ALLOW_FALLBACK", "1")  # לפולבק python-binance

def _http(user_agent: str = "algogpt/executor") -> httpx.Client:
    return httpx.Client(
        http2=HTTP2_ENABLE,
        timeout=BINANCE_HTTP_TIMEOUT,
        headers={"User-Agent": user_agent},
    )

# ---------- Utils layer (עדיף כשזמין) ----------
def _utils_balance() -> Optional[List[Dict[str, Any]]]:
    if not EXECUTOR_USE_UTILS:
        return None
    try:
        from utils.binance_client import futures_balance  # type: ignore
        return futures_balance()
    except Exception:
        return None

def _utils_positions() -> Optional[List[Dict[str, Any]]]:
    if not EXECUTOR_USE_UTILS:
        return None
    try:
        from utils.binance_client import get_open_positions  # type: ignore
        items = get_open_positions() or []
        # סינון 0-size
        try:
            items = [p for p in items if abs(float(p.get("positionAmt") or 0)) != 0]
        except Exception:
            pass
        return items
    except Exception:
        return None

def _utils_mark_price(symbol: str) -> Optional[float]:
    if not EXECUTOR_USE_UTILS:
        return None
    try:
        from utils.binance_client import futures_mark_price  # type: ignore
        px = futures_mark_price(symbol)
        return float(px) if px is not None else None
    except Exception:
        return None

# ---------- Fallback: python-binance ----------
def _pb_positions() -> List[Dict[str, Any]]:
    if not EXECUTOR_ALLOW_FALLBACK:
        raise HTTPException(status_code=501, detail="utils layer required (fallback disabled)")
    try:
        from binance.client import Client  # type: ignore
    except Exception:
        raise HTTPException(status_code=501, detail="python-binance not installed")
    try:
        testnet = _flag("BINANCE_TESTNET", "0")
        cli = Client(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", ""), testnet=testnet)
        res = cli.futures_position_information() or []
        res = [p for p in res if abs(float(p.get("positionAmt") or 0)) != 0]
        return res
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[executor] python-binance positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def _pb_balance() -> List[Dict[str, Any]]:
    if not EXECUTOR_ALLOW_FALLBACK:
        raise HTTPException(status_code=501, detail="utils layer required (fallback disabled)")
    try:
        from binance.client import Client  # type: ignore
    except Exception:
        raise HTTPException(status_code=501, detail="python-binance not installed")
    try:
        testnet = _flag("BINANCE_TESTNET", "0")
        cli = Client(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", ""), testnet=testnet)
        return cli.futures_account_balance() or []
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[executor] python-binance balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# ---------- Symbol filtering ----------
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

# ---------- Endpoints ----------
@router.get("/positions", summary="List open futures positions")
def list_positions() -> Dict[str, Any]:
    """
    עדיפות: utils.binance_client → פולבק python-binance (אם EXECUTOR_ALLOW_FALLBACK=1).
    """
    items = _utils_positions()
    if items is not None:
        return {"ok": True, "items": items, "count": len(items)}
    # fallback
    res = _pb_positions()
    return {"ok": True, "items": res, "count": len(res)}

@router.get("/balance", summary="Get futures account balance")
def get_balance() -> Dict[str, Any]:
    """
    עדיפות: utils.binance_client → פולבק python-binance (אם EXECUTOR_ALLOW_FALLBACK=1).
    """
    bal = _utils_balance()
    if bal is not None:
        return {"ok": True, "balances": bal}
    res = _pb_balance()
    return {"ok": True, "balances": res}

@router.get("/mark-price", summary="Get futures mark price")
def get_mark_price(symbol: str = Query(..., description="e.g. BTCUSDT")) -> Dict[str, Any]:
    """
    Mark Price:
    - נסה utils קודם.
    - אם לא, משוך מ־/fapi/v1/premiumIndex.
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=422, detail="symbol required")

    upx = _utils_mark_price(sym)
    if upx is not None:
        return {"ok": True, "symbol": sym, "markPrice": float(upx)}

    url = f"{FAPI}/fapi/v1/premiumIndex"
    try:
        with _http() as c:
            r = c.get(url, params={"symbol": sym})
            r.raise_for_status()
            data = r.json()
            mp = float(data.get("markPrice"))
            return {"ok": True, "symbol": sym, "markPrice": mp}
    except Exception as e:
        logger.exception("[executor] mark-price error: %s", e)
        raise HTTPException(status_code=502, detail="mark price unavailable")

@router.get("/exchange-info", summary="Raw Binance futures exchangeInfo (slim)")
def get_exchange_info() -> Dict[str, Any]:
    """
    משיכת exchangeInfo מ-FAPI והחזרת גרסה "רזה" עבור לקוחות/דאשבורד.
    """
    url = f"{FAPI}/fapi/v1/exchangeInfo"
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
    """
    רשימת סימבולים סחירים USDT-M (TRADING; perpetual/quarterly).
    """
    url = f"{FAPI}/fapi/v1/exchangeInfo"
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






