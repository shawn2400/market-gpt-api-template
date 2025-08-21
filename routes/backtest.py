# routes/backtest.py
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from utils.backtest_utils import run_backtest

router = APIRouter(tags=["Backtest"])

# =====================
# Models
# =====================
class BacktestTrade(BaseModel):
    side: str
    entry: float
    exit: float
    pnl: float

class BacktestSummary(BaseModel):
    n_trades_total: int
    n_trades_returned: int
    final_balance: float
    profit_pct: float

class BacktestResult(BaseModel):
    ok: bool = True
    symbol: str
    strategy: str
    summary: BacktestSummary
    trades: List[BacktestTrade] = Field(default_factory=list)

# =====================
# Endpoint
# =====================
@router.get("/", response_model=BacktestResult)
async def backtest(
    symbol: str,
    strategy: str = Query("ema_crossover", description="Strategy name"),
    limit: int = Query(500, ge=50, le=1000, description="מספר נרות היסטוריים לבדיקה"),
    max_trades: int = Query(200, ge=50, le=500, description="מספר מקסימלי של טריידים שיוחזרו ללקוח"),
):
    """
    מריץ Backtest (מוגבל ל־1000 candles).
    מחזיר עד `max_trades` טריידים אחרונים + summary מסכם.
    """
    raw: Dict[str, Any] = run_backtest(
        df=None,  # ⬅️ בפועל צריך לשלוף DF לפי symbol (ראה utils.data_fetcher / klines)
        strategy=strategy,
        initial_balance=1000.0,
        max_trades=max_trades,
    )

    # ✅ הכנה למודל
    summary = BacktestSummary(
        n_trades_total=raw["summary"]["n_trades_total"],
        n_trades_returned=raw["summary"]["n_trades_returned"],
        final_balance=raw["summary"]["final_balance"],
        profit_pct=raw["summary"]["profit_pct"],
    )

    trades = [BacktestTrade(**t) for t in raw.get("trades", [])]

    return BacktestResult(
        ok=True,
        symbol=symbol,
        strategy=strategy,
        summary=summary,
        trades=trades,
    )














