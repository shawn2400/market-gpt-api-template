# routes/trade.py
from __future__ import annotations

import logging
from typing import Literal, Annotated, Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from utils.auth import require_bearer_token
from utils.sl_tp_utils import calculate_sl_tp
from utils.metrics import metrics_tracker

router = APIRouter(prefix="/trade", tags=["Trade"])

# ---- Models ----
class TradeRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: Literal["LONG", "SHORT"] = Field(..., example="LONG")
    budget: float = Field(30, ge=0.01)
    leverage: int = Field(10, ge=1, le=125)
    entry: Optional[float] = Field(None, description="אם לא נשלח - ייקח מחיר חי")
    sl: Optional[float] = None
    tp: Optional[float] = None
    dry_run: bool = True
    atr: Optional[float] = Field(None, description="אופציונלי - אם נשלח נשתמש לחישוב SL/TP")

class SLTPRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    direction: Literal["LONG", "SHORT"]
    entry: float = Field(..., gt=0)
    atr: Optional[float] = Field(None, description="אופציונלי")

# ---- Helpers ----
_BINANCE_FAPI = "https://fapi.binance.com"

async def _get_price(symbol: str) -> float:
    """Fetch latest futures ticker price from Binance FAPI."""
    url = f"{_BINANCE_FAPI}/fapi/v1/ticker/price"
    async with httpx.AsyncClient(timeout=8.0) as x:
        r = await x.get(url, params={"symbol": symbol.upper()})
    r.raise_for_status()
    j = r.json()
    price = float(j.get("price"))
    if price <= 0:
        raise RuntimeError(f"invalid price from Binance for {symbol}")
    return price

def _derive_tp2(entry: float, tp1: float, direction: str) -> float:
    # TP2 מעט אגרסיבי יותר: 1.6x מהמרחק של TP1
    if direction == "LONG":
        return round(entry + (tp1 - entry) * 1.6, 6)
    return round(entry - (entry - tp1) * 1.6, 6)

# ---- Routes ----

@router.post(
    "/sltp",
    operation_id="postTradeSuggestSLTP",
    dependencies=[Depends(require_bearer_token)],
)
async def suggest_sltp(req: SLTPRequest):
    """
    מציע SL/TP לפי ATR (אם קיים) או רצפות אחוזיות מוגדרות.
    """
    try:
        sl, tp1 = calculate_sl_tp(
            entry_price=req.entry,
            direction=req.direction,
            atr=req.atr,
        )
        tp2 = _derive_tp2(req.entry, tp1, req.direction)
        return {"symbol": req.symbol.upper(), "direction": req.direction, "sl": sl, "tp1": tp1, "tp2": tp2}
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=f"SLTP calc failed: {e}")

@router.post(
    "/execute",
    operation_id="postTradeExecute",
    dependencies=[Depends(require_bearer_token)],
)
async def execute_trade(trade: TradeRequest):
    """
    ביצוע טרייד. אם חסר SL/TP נחשב אוטומטית. ברירת מחדל dry_run=true.
    """
    try:
        entry = float(trade.entry) if trade.entry else await _get_price(trade.symbol)
        sl = trade.sl
        tp = trade.tp

        # אם לא הגיעו sl/tp – נחשב
        if sl is None or tp is None:
            calc_sl, calc_tp1 = calculate_sl_tp(
                entry_price=entry,
                direction=trade.side,
                atr=trade.atr,
            )
            sl = calc_sl if sl is None else sl
            tp = calc_tp1 if tp is None else tp

        # dry-run מחזיר תוכנית בלבד (ללא ביצוע)
        if trade.dry_run:
            plan = {
                "mode": "dry_run",
                "symbol": trade.symbol.upper(),
                "side": trade.side,
                "entry": round(entry, 6),
                "sl": sl,
                "tp": tp,
                "leverage": trade.leverage,
                "budget": trade.budget,
            }
            logging.info("[DRY-RUN] %s", plan)
            return {"status": "ok", "result": plan}

        # ביצוע חי (פנימי)
        try:
            from utils.binance_trader import binance_futures_trade  # ייכשל אם EXECUTE_TRADES=false או חסר קונפיג
        except Exception as ie:
            raise RuntimeError(f"live trading module unavailable: {ie}")

        result = await binance_futures_trade(
            symbol=trade.symbol,
            side=trade.side,
            entry=entry,
            sl=sl,
            tp=tp,
            leverage=trade.leverage,
            budget=trade.budget,
        )
        return {"status": "ok", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))











