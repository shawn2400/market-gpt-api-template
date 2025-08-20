# routes/trade.py
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from utils.sltp import calc_sl_tp

router = APIRouter(tags=["Trading"])

class TradeRequest(BaseModel):
    symbol: str
    side: str = Field(..., description="LONG or SHORT")
    type: str = Field("LIMIT", description="LIMIT or STOP_LIMIT")
    price: float
    quantity: float
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    atr: Optional[float] = None
    dry_run: bool = True

@router.post("/execute", summary="Execute Trade (LIVE or Dry Run)")
async def execute_trade(req: TradeRequest) -> Dict[str, Any]:
    try:
        side = req.side.upper()
        if side not in ("LONG", "SHORT"):
            return {"ok": False, "error": "side must be LONG or SHORT"}

        entry_price = req.entry or req.price
        sl_price, tp_price = calc_sl_tp(entry=entry_price, side=side, sl=req.sl, tp=req.tp, atr=req.atr)

        if not req.dry_run:
            # 🔴 כאן יבוא חיבור אמיתי ל־Binance
            pass

        return {
            "ok": True,
            "dry_run": req.dry_run,
            "symbol": req.symbol,
            "side": side,
            "entry": entry_price,
            "price": req.price,
            "qty": req.quantity,
            "sl": sl_price,
            "tp": tp_price,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}



















































































































































































































































































































