# routes/backtest.py
from fastapi import APIRouter, Query
from typing import Dict, Any
import logging
import pandas as pd
from binance.client import Client

from utils.config import BINANCE_API_KEY, BINANCE_API_SECRET
from utils.backtest_utils import run_backtest  # ✅ שימוש נכון

logger = logging.getLogger("algogpt.backtest")
router = APIRouter(prefix="/backtest", tags=["Backtest"])

_client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)


async def fetch_klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    raw = _client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "num_trades", "taker_base", "taker_quote", "ignore"
    ])
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    return df


@router.get("/", summary="Run backtest", operation_id="runBacktest")
async def backtest(
    symbol: str = Query(..., description="Trading pair, e.g. BTCUSDT"),
    interval: str = Query("15m", description="Candle interval"),
    limit: int = Query(500, ge=50, le=1000),
    strategy: str = Query("ema_crossover", description="Strategy name"),
) -> Dict[str, Any]:
    try:
        df = await fetch_klines(symbol, interval, limit)
        result = run_backtest(df, strategy=strategy)
        result.update({"symbol": symbol, "interval": interval})
        return result
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        return {"ok": False, "error": str(e)}










