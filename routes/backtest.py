# routes/backtest.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal
from utils.auth import require_bearer_token
from utils.backtest_utils import run_backtest_for_symbol
from utils.metrics import metrics_tracker

router = APIRouter()

class BacktestRequest(BaseModel):
    symbol: str
    timeframe: Literal["5m", "15m", "1h", "4h"] = "15m"
    limit: int = 200
    slippage_pct: float = 0.1

@router.post("/backtest", tags=["Backtest"], dependencies=[Depends(require_bearer_token)])
async def backtest(req: BacktestRequest):
    try:
        result = await run_backtest_for_symbol(
            symbol=req.symbol,
            timeframe=req.timeframe,
            limit=req.limit,
            slippage_pct=req.slippage_pct,
        )
        # שומרים את מבנה התגובה כפי שהיה אצלך (status + backtest)
        return {"status": "ok", "backtest": result}
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))






