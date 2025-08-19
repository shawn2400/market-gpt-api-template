# routes/price.py
from __future__ import annotations
from typing import Literal, Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

# ---- Auth (קשיח, לא מפיל שרת במקרה באג פנימי) ----
try:
    from utils.auth import require_bearer_token as _raw_require_bearer  # type: ignore

    def require_bearer_token():
        try:
            return _raw_require_bearer()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized")
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(tags=["Price"], dependencies=[Depends(require_bearer_token)])

# ---- Fallback providers ----
async def _smart_price(symbol: str, market: str) -> Optional[float]:
    """
    נסה first-class WS+REST; חזור None אם אין/נכשל.
    """
    try:
        from utils.ws_fallback import get_price_smart  # type: ignore
        p = await get_price_smart(symbol)
        return float(p) if p else None
    except Exception:
        return None

def _futures_mark_price(symbol: str) -> Optional[float]:
    try:
        from utils.binance_client import futures_mark_price  # type: ignore
        data = futures_mark_price(symbol)
        if isinstance(data, dict) and data.get("ok"):
            mp = data.get("markPrice")
            return float(mp) if mp is not None else None
    except Exception:
        pass
    return None

def _spot_rest_price(symbol: str) -> Optional[float]:
    try:
        import os, requests
        base = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com").rstrip("/")
        r = requests.get(f"{base}/api/v3/ticker/price", params={"symbol": symbol}, timeout=5)
        r.raise_for_status()
        data = r.json()
        return float(data.get("price"))
    except Exception:
        return None

# ---- Core get ----
async def _get_price(symbol: str, market: Literal["futures","spot"], source: Literal["smart","mark","rest"]) -> Dict[str, Any]:
    sym = symbol.upper().strip()
    now = datetime.now(tz=timezone.utc).isoformat()
    price: Optional[float] = None
    used: str = source

    if source == "smart":
        price = await _smart_price(sym, market)
        if price is None:
            # fallback לפי שוק
            if market == "futures":
                price = _futures_mark_price(sym)
                used = "mark"
            else:
                price = _spot_rest_price(sym)
                used = "rest"
    elif source == "mark":
        if market != "futures":
            raise HTTPException(status_code=400, detail="source=mark valid only for market=futures")
        price = _futures_mark_price(sym)
    else:  # rest
        price = _spot_rest_price(sym) if market == "spot" else _futures_mark_price(sym)

    if price is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Upstream price unavailable")

    return {"ok": True, "symbol": sym, "market": market, "price": float(price), "source": used, "now_utc": now}

# ---- Endpoints ----
@router.get("/price")
async def get_price(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    market: Literal["futures","spot"] = Query("futures"),
    source: Literal["smart","mark","rest"] = Query("smart"),
):
    return await _get_price(symbol, market, source)

@router.get("/price/{symbol}")
async def get_price_path(
    symbol: str,
    market: Literal["futures","spot"] = Query("futures"),
    source: Literal["smart","mark","rest"] = Query("smart"),
):
    return await _get_price(symbol, market, source)

