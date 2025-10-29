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

# ---- soft auth shim (אם utils.auth לא קיים) ----
try:
    from utils.auth import require_api_key  # type: ignore
except Exception:
    async def require_api_key(request: Request):
        """
        הגנה בסיסית עם Bearer Token (קבוע בזמן) אם PROTECT_EXECUTOR_ROUTES=1.
        """
        protect = os.getenv("PROTECT_EXECUTOR_ROUTES", "1").lower() in ("1", "true", "yes", "on")
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

_FAPI = os.getenv("BINANCE_FAPI", "https://fapi.binance.com").rstrip("/")


def _env_flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").lower() in ("1", "true", "yes", "on")


def _http() -> httpx.Client:
    # חיבור HTTP יעיל עם timeout סביר וכותרת UA
    return httpx.Client(
        http2=_env_flag("HTTP2_ENABLE", "1"),
        timeout=float(os.getenv("BINANCE_HTTP_TIMEOUT", "10.0")),
        headers={"User-Agent": "algogpt/executor"},
    )


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


# ---------- helpers (optional utils.binance_client) ----------
def _utils_balance() -> Optional[List[Dict[str, Any]]]:
    try:
        from utils.binance_client import futures_balance  # type: ignore
        return futures_balance()
    except Exception:
        return None


def _utils_positions() -> Optional[List[Dict[str, Any]]]:
    try:
        from utils.binance_client import get_open_positions  # type: ignore
        return get_open_positions() or []
    except Exception:
        return None


def _utils_mark_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import futures_mark_price  # type: ignore
        px = futures_mark_price(symbol)
        return float(px) if px is not None else None
    except Exception:
        return None


@router.get("/positions", summary="List open futures positions")
def list_positions() -> Dict[str, Any]:
    """
    מחזיר פוזיציות פתוחות:
    1) דרך utils.binance_client אם קיים
    2) נפילה רכה ל-python-binance אם מותקן
    """
    # נסה utils קודם
    items = _utils_positions()
    if items is not None:
        try:
            # שמירה רק על פוזיציות עם כמות != 0 במידה וקלט מלא
            items = [p for p in items if abs(float(p.get("positionAmt") or 0)) != 0]
        except Exception:
            pass
        return {"ok": True, "items": items, "count": len(items)}

    # fallback ל-python-binance
    try:
        from binance.client import Client  # type: ignore
        testnet = _env_flag("BINANCE_TESTNET", "0")
        cli = Client(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", ""), testnet=testnet)
        res = cli.futures_position_information() or []
        res = [p for p in res if abs(float(p.get("positionAmt") or 0)) != 0]
        return {"ok": True, "items": res, "count": len(res)}
    except ImportError:
        raise HTTPException(status_code=501, detail="python-binance not installed")
    except Exception as e:
        logger.exception("[executor] positions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance", summary="Get futures account balance")
def get_balance() -> Dict[str, Any]:
    """
    מחזיר יתרות Futures:
    1) דרך utils.binance_client אם קיים
    2) נפילה רכה ל-python-binance אם מותקן
    """
    bal = _utils_balance()
    if bal is not None:
        return {"ok": True, "balances": bal}
    try:
        from binance.client import Client  # type: ignore
        testnet = _env_flag("BINANCE_TESTNET", "0")
        cli = Client(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", ""), testnet=testnet)
        res = cli.futures_account_balance()
        return {"ok": True, "balances": res}
    except ImportError:
        raise HTTPException(status_code=501, detail="python-binance not installed")
    except Exception as e:
        logger.exception("[executor] balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mark-price", summary="Get futures mark price")
def get_mark_price(symbol: str = Query(..., description="e.g. BTCUSDT")) -> Dict[str, Any]:
    """
    מחזיר Mark Price עבור סימבול. מנסה תחילה utils, נופל ל־/premiumIndex.
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=422, detail="symbol required")

    # utils first
    upx = _utils_mark_price(sym)
    if upx is not None:
        return {"ok": True, "symbol": sym, "markPrice": float(upx)}

    # HTTP premiumIndex
    url = f"{_FAPI}/fapi/v1/premiumIndex"
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
    משיכת exchangeInfo מ-FAPI והחזרת גרסה "רזה": סימבול/נכסים/סטטוס/פילטרים חיוניים.
    """
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
    """
    מחזיר רשימת סימבולים סחירים USDT-M (TRADING; perpetual/quarterly).
    """
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





