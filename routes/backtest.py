# routes/backtest.py
from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

# --- Auth wrapper ---
try:
    from utils.auth import require_bearer_token as _raw_require_bearer
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return _raw_require_bearer(authorization=authorization)
except Exception:
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return None

router = APIRouter(prefix="/backtest", tags=["Backtest"], dependencies=[Depends(require_bearer_token)])


# --- Models ---
class BacktestRequest(BaseModel):
    symbol: str
    side: str
    interval: str = "15m"
    lookback_days: int = 30
    leverage: Optional[int] = 5


class BacktestResult(BaseModel):
    symbol: str
    side: str
    interval: str
    lookback_days: int
    trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float


class BacktestResponse(BaseModel):
    ok: bool
    results: List[BacktestResult]


# --- Endpoints ---
@router.post("/", response_model=BacktestResponse, summary="Run backtest", operation_id="postRunBacktest")
async def run_backtest(req: BacktestRequest):
    """
    מבצע סימולציית Backtest על נתוני העבר.
    """
    # דמה בלבד – במציאות יחושב לפי נתוני היסטוריית שוק
    result = BacktestResult(
        symbol=req.symbol.upper(),
        side=req.side.upper(),
        interval=req.interval,
        lookback_days=req.lookback_days,
        trades=42,
        win_rate=61.9,
        avg_pnl=2.5,
        total_pnl=105.0,
    )
    return BacktestResponse(ok=True, results=[result])


@router.get("/status/{symbol}", summary="Get last backtest status", operation_id="getBacktestStatus")
async def get_backtest_status(symbol: str):
    """
    מחזיר סטטוס אחרון של Backtest עבור סמל נתון.
    """
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "last_run": "2025-08-20T10:00:00Z",
        "trades": 42,
        "win_rate": 61.9,
        "total_pnl": 105.0,
    }









