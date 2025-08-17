from typing import Literal
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from utils.auth import require_bearer_token
from utils.metrics import metrics_tracker
from utils.backtest_utils import run_backtest_for_symbol

router = APIRouter()

class BacktestRequest(BaseModel):
    symbol: str
    timeframe: Literal["5m", "15m", "1h", "4h"] = "15m"
    limit: int = 200
    slippage_pct: float = 0.1

@router.post(
    "/backtest",
    tags=["Backtest"],
    operation_id="postBacktestRun",
    summary="Run strategy backtest for a symbol",
)
async def backtest(
    req: BacktestRequest,
    _: None = Depends(require_bearer_token),
):
    try:
        result = await run_backtest_for_symbol(
            symbol=req.symbol,
            timeframe=req.timeframe,
            limit=req.limit,
            slippage_pct=req.slippage_pct,
        )
        return result  # כבר בפורמט BacktestResult
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))







