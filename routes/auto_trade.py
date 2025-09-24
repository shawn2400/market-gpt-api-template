# routes/auto_trade.py
from __future__ import annotations
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.strategy_auto import pick_side_for_symbol
from utils.trade_executor import execute_trade_live  # מבצע בפועל בורסה

router = APIRouter(prefix="/auto", tags=["Auto Trade"])

class AutoTradeReq(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"])
    budget_usd: float = Field(..., gt=0, examples=[10])
    leverage: int = Field(..., ge=1, le=125, examples=[10])
    quantity: Optional[float] = Field(None, gt=0)  # אופציונלי: אם לא — יחושב ע"פ תקציב
    dry_run: bool = False
    confirm_first: bool = False
    # אילוץ-צד ידני (לא חובה): "LONG"/"SHORT"
    force_position_side: Optional[str] = None

@router.post("/trade")
async def auto_trade(req: AutoTradeReq, _token: str = Depends(require_api_key)) -> Dict[str, Any]:
    """
    בחירת LONG/SHORT דינמית → ביצוע טרייד עם TP/SL אוטומטיים (לפי ENV של ה־executor/manager).
    """
    # אם המשתמש לא אילץ צד — בחר אוטומטית
    if req.force_position_side:
        ps = req.force_position_side.strip().upper()
        if ps not in ("LONG", "SHORT"):
            raise HTTPException(status_code=422, detail="force_position_side must be LONG or SHORT")
        side = "BUY" if ps == "LONG" else "SELL"
        position_side = ps
        reason = "forced_by_request"
    else:
        side, position_side, reason = await pick_side_for_symbol(req.symbol)

    # מבצעים את הטרייד (ה־trade_executor מכיל TP/SL/BE/Ladder לפי ENV)
    try:
        res = await execute_trade_live(
            symbol=req.symbol,
            side=side,                 # BUY/SELL
            budget=req.budget_usd,
            leverage=req.leverage,
            dry_run=req.dry_run,
            quantity=req.quantity,     # יכול להיות None → המנוע יחשב
            position_side=position_side,  # LONG/SHORT
            confirm_first=req.confirm_first,
        )
        return {
            "ok": True,
            "error": None,
            "result": res,
            "decider": {"side": side, "position_side": position_side, "reason": reason},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


