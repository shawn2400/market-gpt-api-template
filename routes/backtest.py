# routes/backtest.py
from __future__ import annotations
import logging
from fastapi import APIRouter, Query
from typing import Dict, Any

from utils.backtester import run_backtest   # נניח שכבר בנית utils/backtester.py

router = APIRouter(prefix="/backtest", tags=["Backtest"])
logger = logging.getLogger("algogpt.backtest")


@router.get("/run", summary="Run Backtest on symbol")
async def backtest_run(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: str = Query("15m", description="Candlestick interval (e.g. 1m, 5m, 15m, 1h, 4h)"),
    limit: int = Query(500, ge=50, le=1000, description="Number of candles to fetch"),
    strategy: str = Query("ema_rsi", description="Which strategy to test"),
    initial_balance: float = Query(1000.0, description="Starting balance in USDT"),
) -> Dict[str, Any]:
    """
    מריץ סימולציית Backtest היסטורית עם נתונים מ-Binance.
    """
    try:
        result = await run_backtest(
            symbol=symbol.upper(),
            interval=interval,
            limit=limit,
            strategy=strategy,
            initial_balance=initial_balance,
        )
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception("Backtest run failed")
        return {"ok": False, "error": str(e)}


@router.get("/status", summary="Backtest status")
async def backtest_status() -> Dict[str, Any]:
    """
    בודק אם מערכת ה-Backtest זמינה
    """
    return {"ok": True, "status": "ready"}










