# routes/auto_trade.py
from __future__ import annotations
from typing import Optional, Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.strategy_auto import pick_side_for_symbol
from utils.trade_executor import execute_trade_live  # המבצע בפועל בבורסה

router = APIRouter(prefix="/auto", tags=["Auto Trade"])

class AutoTradeReq(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"])
    budget_usd: float = Field(..., gt=0, examples=[10])
    leverage: int = Field(..., ge=1, le=125, examples=[10])
    quantity: Optional[float] = Field(None, gt=0)   # אם None – יחושב מתוך התקציב
    dry_run: bool = False
    confirm_first: bool = False
    # אילוץ צד ידני (לא חובה): "LONG"/"SHORT"
    force_position_side: Optional[str] = None

async def _decide_side(symbol: str, forced: Optional[str]) -> Tuple[str, str, str]:
    """מחזיר (side, position_side, reason)"""
    if forced:
        ps = forced.strip().upper()
        if ps not in ("LONG", "SHORT"):
            raise HTTPException(status_code=422, detail="force_position_side must be LONG or SHORT")
        side = "BUY" if ps == "LONG" else "SELL"
        return side, ps, "forced_by_request"
    return await pick_side_for_symbol(symbol)

@router.post("/trade")
async def auto_trade(req: AutoTradeReq, _tok: str = Depends(require_api_key)) -> Dict[str, Any]:
    """
    בחירה דינמית של LONG/SHORT → ביצוע טרייד דרך execute_trade_live.
    אין העברת note לפונקציה (כדי למנוע unexpected keyword).
    """
    symbol = req.symbol.strip().upper()
    side, position_side, reason = await _decide_side(symbol, req.force_position_side)

    try:
        # שים לב: הפרמטר הנכון הוא budget_usd (לא "budget")
        res = await execute_trade_live(
            symbol=symbol,
            side=side,                          # BUY/SELL
            position_side=position_side,        # LONG/SHORT
            budget_usd=req.budget_usd,          # ← הפרמטר התקין
            leverage=req.leverage,
            quantity=req.quantity,              # יכול להיות None
            confirm_first=req.confirm_first,
            dry_run=req.dry_run,
        )
        return {
            "ok": True,
            "error": None,
            "result": res,
            "decider": {"side": side, "position_side": position_side, "reason": reason},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


