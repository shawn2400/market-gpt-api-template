# routes/auto_trade.py
from __future__ import annotations
from typing import Optional, Dict, Any
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.strategy_auto import pick_side_for_symbol
from utils.trade_executor import execute_trade_live  # מבצע בפועל בורסה
from utils.execution_bot import ExecutionBot

router = APIRouter(prefix="/auto", tags=["Auto Trade"])
logger = logging.getLogger("algogpt.auto_trade")

_auto_trade_execution_bot = ExecutionBot(logger=logger)

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

    # מבצעים את הטרייד דרך ExecutionBot
    try:
        ticket_exec = {
            "symbol": req.symbol,
            "side": side,
            "budget": req.budget_usd,
            "budget_usd": req.budget_usd,
            "leverage": req.leverage,
            "dry_run": req.dry_run,
            "quantity": req.quantity,
            "qty": req.quantity,
            "position_side": position_side,
            "confirm_first": req.confirm_first,
            "require_approval": req.confirm_first,
        }
        
        result = await _auto_trade_execution_bot.open_position(ticket_exec, source="auto_trade")
        ok = result.get("status") == "opened"
        
        return {
            "ok": ok,
            "error": None if ok else result.get("reason"),
            "result": {
                "ok": ok,
                "position_id": result.get("position_id"),
                "entry_orders": result.get("entry_orders"),
                "sl_order": result.get("sl_order"),
                "tp_orders": result.get("tp_orders"),
                "symbol": result.get("symbol"),
                "side": result.get("side"),
                "flow": result.get("flow"),
                "reason": result.get("reason"),
            },
            "decider": {"side": side, "position_side": position_side, "reason": reason},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


