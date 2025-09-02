# routes/precision.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any

from utils.precision_utils import (
    refresh_exchange_info,
    get_precision_info,
    apply_price_tick,
    apply_price_tick_side,
    apply_qty_step,
    calc_quantity_from_budget,
)

router = APIRouter(prefix="/precision", tags=["Precision"])

# --------- Schemas ---------
class AlignRequest(BaseModel):
    symbol: str = Field(..., description="e.g. LINKUSDT")
    side: Optional[Literal["BUY", "SELL"]] = Field(None, description="Optional, for price ceil/floor logic")
    price: Optional[float] = Field(None, description="Desired limit price to align to tick")
    qty: Optional[float] = Field(None, description="Desired quantity to align to step")


class CalcQtyRequest(BaseModel):
    symbol: str
    price: float
    budget_usd: float = Field(..., gt=0)
    leverage: float = Field(1.0, gt=0)


# --------- Endpoints ---------
@router.get("/info")
def precision_info(symbol: str):
    """
    מחזיר pricePrecision/quantityPrecision מתוך exchangeInfo (עם cache).
    """
    try:
        data = get_precision_info(symbol)
        return {"ok": True, "symbol": symbol.upper(), "precision": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"precision_info failed: {e}")


@router.post("/align")
def align_payload(req: AlignRequest):
    """
    יישור price ו/או qty לפי tick/step של הסימבול.
    אם side=SELL → מחיר מעוגל מעלה (בטוח), אחרת מעוגל מטה.
    """
    s = (req.symbol or "").upper().strip()
    if not s:
        raise HTTPException(status_code=400, detail="symbol is required")

    out: Dict[str, Any] = {"symbol": s}

    try:
        if req.price is not None:
            if (req.side or "").upper() in ("BUY", "SELL"):
                p_dec, p_str = apply_price_tick_side(float(req.price), s, req.side)  # BUY=DOWN / SELL=UP
            else:
                p_dec, p_str = apply_price_tick(float(req.price), s)
            out.update({"price_in": req.price, "price_aligned": p_dec, "price_str": p_str})

        if req.qty is not None:
            q_dec, q_str = apply_qty_step(float(req.qty), s)
            out.update({"qty_in": req.qty, "qty_aligned": q_dec, "qty_str": q_str})

        if "price_in" not in out and "qty_in" not in out:
            raise HTTPException(status_code=400, detail="provide price and/or qty")

        return {"ok": True, **out}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"align failed: {e}")


@router.post("/calc-qty")
def calc_qty(req: CalcQtyRequest):
    """
    מחשב כמות לפי תקציב×מינוף, מכבד LOT_SIZE ו-MIN_NOTIONAL.
    """
    try:
        res = calc_quantity_from_budget(
            req.symbol,
            price=float(req.price),
            budget_usd=float(req.budget_usd),
            leverage=float(req.leverage),
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"calc-qty failed: {e}")


@router.post("/refresh")
def refresh():
    """
    ריענון יזום ל-exchangeInfo cache (לשינויים בפילטרים/precision בבורסה).
    """
    try:
        refresh_exchange_info()
        return {"ok": True, "refreshed": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"refresh failed: {e}")

