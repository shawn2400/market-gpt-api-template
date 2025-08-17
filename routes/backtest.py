# routes/backtest.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal, Optional, Any, Dict, List
from utils.auth import require_bearer_token
from utils.scanner_utils import fetch_ohlcv
from utils.backtest_utils import run_backtest
from utils.metrics import metrics_tracker

router = APIRouter()

class BacktestRequest(BaseModel):
    symbol: str
    timeframe: Literal["5m", "15m", "1h", "4h"] = "15m"
    limit: int = 200
    slippage_pct: float = 0.1  # שמור לשימוש עתידי

@router.post("/backtest", tags=["Backtest"], operation_id="postBacktestRun")
async def backtest(
    req: BacktestRequest,
    _: None = Depends(require_bearer_token),
):
    try:
        df = await fetch_ohlcv(req.symbol, interval=req.timeframe, limit=req.limit)
        if df.empty:
            raise HTTPException(status_code=404, detail="אין נתונים לסימבול/טיימפריים המבוקשים")
        trades_df = run_backtest(df)
        trades: List[Dict[str, Any]] = trades_df.to_dict(orient="records") if not trades_df.empty else []
        payload = {
            "symbol": req.symbol.upper(),
            "timeframe": req.timeframe,
            "count": len(trades),
            "trades": trades,
        }
        return {"status": "ok", "backtest": payload}
    except HTTPException:
        raise
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))




