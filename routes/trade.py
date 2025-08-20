# routes/trade.py
from __future__ import annotations
from fastapi import APIRouter, Body
from typing import Dict, Any, Literal

router = APIRouter(tags=["Trade"])

# ✅ LIVE trade execute (לא demo)
@router.post("/execute", summary="Execute Trade (with dry_run option)")
async def trade_execute(
    symbol: str = Body(..., description="Trading pair e.g. BTCUSDT"),
    side: Literal["LONG", "SHORT"] = Body(..., description="Position side: LONG or SHORT"),
    type: Literal["LIMIT", "STOP_LIMIT"] = Body(..., description="Order type"),
    price: float = Body(..., gt=0),
    quantity: float = Body(..., gt=0),
    entry: float | None = Body(None, description="Required for SL/TP auto-calc"),
    sl: float | None = Body(None, description="Stop Loss"),
    tp: float | None = Body(None, description="Take Profit"),
    dry_run: bool = Body(True, description="If true, no real order is placed"),
) -> Dict[str, Any]:
    # אם אין entry והמשתמש רוצה SL/TP → נחזיר 400
    if (sl or tp) and not entry:
        return {"ok": False, "error": "entry is required when auto-calculating SL/TP"}

    # פה נכנסת הלוגיקה למסחר אמיתי ב־Binance
    order = {
        "symbol": symbol,
        "side": side,
        "type": type,
        "price": price,
        "quantity": quantity,
        "dry_run": dry_run,
        "sl": sl,
        "tp": tp,
        "entry": entry,
    }

    # ⚡ כרגע רק מחזיר JSON (אפשר להוסיף חיבור ל־Binance API בהמשך)
    return {"ok": True, "executed": order}


















































































































































































































































































































