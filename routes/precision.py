# routes/precision.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from typing import Dict, Any, Optional

from utils.auth import require_api_key
from utils.precision_utils import (
    refresh_exchange_info,
    apply_price_tick_side,
    calc_quantity_from_budget,
)

router = APIRouter(
    prefix="/precision",
    tags=["Precision"],
    dependencies=[Depends(require_api_key)],
)

@router.post("/refresh")
def api_refresh_exchange_info() -> Dict[str, Any]:
    """ריענון ExchangeInfo מהבורסה (tick/step/minNotional)"""
    refresh_exchange_info()
    return {"ok": True, "refreshed": True}

@router.get("/price")
def api_price_tick(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    price: float = Query(..., description="raw price"),
    side: Optional[str] = Query(None, description="BUY/SELL (אם לא הועבר → floor רגיל)"),
) -> Dict[str, Any]:
    """עיגון מחיר ל-tickSize (עם BUY=down / SELL=up אם side הועבר)"""
    s = (side or "").upper().strip()
    if s in ("BUY", "SELL"):
        dec, s_fmt = apply_price_tick_side(price, symbol, s)
    else:
        # בלי כיוון – נשתמש בביצה של BUY (floor)
        dec, s_fmt = apply_price_tick_side(price, symbol, "BUY")
    return {"ok": True, "symbol": symbol.upper(), "side": s or None, "in": price, "out": dec, "out_str": s_fmt}

@router.get("/qty_from_budget")
def api_qty_from_budget(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    price: float = Query(..., description="entry/mark to compute notional"),
    budget: float = Query(..., description="USD budget before leverage"),
    leverage: float = Query(1.0, description="position leverage"),
) -> Dict[str, Any]:
    """
    כמות לפי תקציב×מינוף, מעוגנת ל-LOT_SIZE ועומדת ב-MIN_NOTIONAL/MIN_QTY אם קיימים.
    """
    res = calc_quantity_from_budget(symbol, price=price, budget_usd=budget, leverage=leverage)
    return {"ok": bool(res.get("ok")), "symbol": symbol.upper(), **res}



