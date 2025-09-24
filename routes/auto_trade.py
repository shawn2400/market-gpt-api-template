# routes/auto_trade.py
from __future__ import annotations
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from utils.auth import require_api_key

# Telegram (best effort)
try:
    from utils.telegram_notifier import send_trade_approval as send_approval  # type: ignore
    from utils.telegram_notifier import notify_ops_alert as send_audit        # type: ignore
except Exception:
    async def send_approval(*args, **kwargs):  # type: ignore
        return None
    async def send_audit(*args, **kwargs):     # type: ignore
        return None

# Strategy + executor
from utils.strategy_auto import decide as decide_auto
try:
    from utils.trade_executor import execute_trade_live  # type: ignore
except Exception:
    execute_trade_live = None  # type: ignore

router = APIRouter(tags=["trade"])

class AutoReq(BaseModel):
    symbol: str
    budget_usd: float = Field(gt=0)
    quantity: Optional[float] = Field(default=None, gt=0)
    confirm_first: bool = True
    dry_run: bool = False
    note: Optional[str] = None

@router.post("/trade/auto")
async def trade_auto(req: AutoReq, _token: str = Depends(require_api_key)) -> Dict[str, Any]:
    if execute_trade_live is None:
        raise HTTPException(status_code=500, detail="trade executor missing")

    try:
        plan = decide_auto(req.symbol, budget_usd=req.budget_usd, qty_override=req.quantity)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"auto_decide_failed: {e}")

    # נבצע/נשלח לאישור – TP/SL נוצרים אוטומטית ע"י ה-executor (LADDER_*=1)
    try:
        res = await execute_trade_live(
            symbol=plan["symbol"],
            side=plan["side"],
            budget=req.budget_usd,
            leverage=plan["leverage"],
            dry_run=req.dry_run,
            quantity=plan["quantity"],
            position_side=plan["position_side"],
            confirm_first=req.confirm_first,
        )
        try:
            await send_audit(f"AUTO-TRADE PLAN · {plan['side']} {plan['symbol']} qty≈{plan['quantity']:.6f} lev={plan['leverage']} (adx={plan['adx']:.1f} ema21={plan['ema21']:.1f} ema50={plan['ema50']:.1f})")
        except Exception:
            pass
        return {"ok": True, "plan": plan, "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"execute_failed: {e}")
