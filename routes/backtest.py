# routes/backtest.py
from __future__ import annotations

from typing import Literal, Optional, List, Dict, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from utils.auth import require_bearer_token
from utils.metrics import metrics_tracker
from utils.scanner_utils import fetch_ohlcv

router = APIRouter(tags=["Backtest"])

class BacktestRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    timeframe: Literal["5m", "15m", "1h", "4h"] = "15m"
    limit: int = Field(200, ge=100, le=1000)
    slippage_pct: float = Field(0.1, ge=0.0, le=5.0, description="אחוז שיחליק את הכניסה/יציאה (0.1% דיפולט)")

class BacktestTrade(BaseModel):
    timestamp: int
    price: float
    side: Literal["LONG", "SHORT"]
    pnl: float

class BacktestResult(BaseModel):
    symbol: str
    timeframe: str
    trades: List[BacktestTrade]
    win_rate: float
    total_pnl: float
    count: int

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

@router.post(
    "/backtest",
    operation_id="postBacktestRun",
    dependencies=[Depends(require_bearer_token)],
    response_model=BacktestResult,
)
async def backtest(req: BacktestRequest):
    """
    Backtest פשוט: אות כניסה כשהסגירה חוצה EMA(50) + כיוון EMA(21)>EMA(50) ללונג ולהפך לשורט.
    יציאה הפוכה (חצייה נגדית). זה backtest מהיר לשימוש מיידי.
    """
    try:
        df = await fetch_ohlcv(req.symbol, interval=req.timeframe, limit=req.limit)
        if df.empty or len(df) < 80:
            raise HTTPException(status_code=404, detail="לא מספיק נתונים ל-backtest")

        close = df["close"].copy()
        ema21 = _ema(close, 21)
        ema50 = _ema(close, 50)

        # כניסה: חציית close את ema50 בכיוון מגובה ע"י ema21/ema50
        sig_long = (close.shift(1) <= ema50.shift(1)) & (close > ema50) & (ema21 > ema50)
        sig_short = (close.shift(1) >= ema50.shift(1)) & (close < ema50) & (ema21 < ema50)

        trades: List[Dict[str, Any]] = []
        pos: Optional[str] = None
        entry_price: Optional[float] = None
        slip = 1.0 + (req.slippage_pct / 100.0)

        for ts, price in close.items():
            if pos is None:
                if bool(sig_long.loc[ts]):
                    pos = "LONG"
                    entry_price = float(price * slip)
                    entry_ts = ts
                elif bool(sig_short.loc[ts]):
                    pos = "SHORT"
                    entry_price = float(price / slip)
                    entry_ts = ts
            else:
                # יציאה כשיש אות הפוך
                if pos == "LONG" and bool(sig_short.loc[ts]):
                    exit_price = float(price / slip)
                    pnl = exit_price - entry_price  # qty=1
                    trades.append({"timestamp": int(entry_ts.value // 10**9), "price": float(exit_price), "side": pos, "pnl": float(pnl)})
                    pos = None
                elif pos == "SHORT" and bool(sig_long.loc[ts]):
                    exit_price = float(price * slip)
                    pnl = entry_price - exit_price
                    trades.append({"timestamp": int(entry_ts.value // 10**9), "price": float(exit_price), "side": pos, "pnl": float(pnl)})
                    pos = None

        wins = sum(1 for t in trades if t["pnl"] > 0)
        total_pnl = float(np.sum([t["pnl"] for t in trades])) if trades else 0.0
        win_rate = float((wins / len(trades) * 100.0) if trades else 0.0)

        return BacktestResult(
            symbol=req.symbol.upper(),
            timeframe=req.timeframe,
            trades=[BacktestTrade(**t) for t in trades],
            win_rate=round(win_rate, 2),
            total_pnl=round(total_pnl, 6),
            count=len(trades),
        )

    except HTTPException:
        raise
    except Exception as e:
        metrics_tracker.record_error()
        raise HTTPException(status_code=500, detail=str(e))





