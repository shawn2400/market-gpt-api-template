# routes/precision.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from typing import Dict, Any, Optional, Tuple

from utils.auth import require_api_key
from utils.precision_utils import (
    refresh_exchange_info,
    apply_price_tick,
    apply_price_tick_side,
    calc_quantity_from_budget,
    get_precision_info,
)

router = APIRouter(
    prefix="/precision",
    tags=["Precision"],
    dependencies=[Depends(require_api_key)],
)

@router.get("/price")
def api_price(
    symbol: str,
    price: float,
    side: Optional[str] = Query(None, description="BUY/SELL (אם נשלח, BUY=roundDown, SELL=roundUp)"),
) -> Dict[str, Any]:
    """
    עיגון מחיר ל-tickSize + pricePrecision.
    side=BUY/SELL מבצע BUY=DOWN, SELL=UP כדי למנוע דחיית הזמנות.
    """
    if side:
        px, s = apply_price_tick_side(price, symbol, side.upper())
    else:
        px, s = apply_price_tick(price, symbol)
    prec = get_precision_info(symbol)
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "input_price": float(price),
        "side": (side or "").upper(),
        "price": float(px),
        "price_str": s,
        "precision": prec,
    }

@router.get("/qty_from_budget")
def api_qty_from_budget(
    symbol: str,
    price: float,
    budget: float,
    leverage: float = 1.0,
) -> Dict[str, Any]:
    """
    חישוב כמות לפי budget×leverage עם כיבוד LOT_SIZE ו-MIN_NOTIONAL.
    מחזיר גם סיבת כשל אם לא עומד במינימוםי הבורסה.
    """
    res = calc_quantity_from_budget(symbol, price=price, budget_usd=budget, leverage=leverage)
    return {"symbol": symbol.upper(), **res}

@router.post("/refresh")
def api_refresh() -> Dict[str, Any]:
    """רענון exchangeInfo מהבורסה (כשיש עדכוני פילטרים/סימבולים)."""
    refresh_exchange_info()
    return {"ok": True}


