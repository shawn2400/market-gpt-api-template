# routes/indicators.py
from __future__ import annotations
from typing import Optional, List
import os, requests, pandas as pd
from fastapi import APIRouter, Query, Path
from pydantic import BaseModel, Field

from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
router = APIRouter(tags=["Indicators"])


# =====================
# Binance helpers
# =====================
def _fetch_klines(symbol: str, interval: str = "1h", limit: int = 180) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=10)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = [
        "open_time","open","high","low","close","volume","close_time",
        "qv","nTrades","taker_base","taker_quote","x"
    ]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]


# =====================
# Models
# =====================
class IndicatorSet(BaseModel):
    rsi: Optional[float] = None
    ema_21: Optional[float] = None
    adx: Optional[float] = None
    atr: Optional[float] = None
    vwap_trend: Optional[bool] = None


class IndicatorSignal(BaseModel):
    symbol: str
    timeframe: str
    indicators: Optional[IndicatorSet] = None
    ok: bool = True
    error: Optional[str] = None


class IndicatorsResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    signals: List[IndicatorSignal] = Field(default_factory=list)
    error: Optional[str] = None


# =====================
# Endpoints
# =====================
@router.get("/", response_model=IndicatorsResponse, operation_id="getIndicatorsSample")
async def get_indicators_sample() -> IndicatorsResponse:
    sample = IndicatorSignal(
        symbol="BTCUSDT",
        timeframe="1h",
        indicators=IndicatorSet(
            rsi=55.2,
            ema_21=123.45,
            adx=18.7,
            atr=2.3,
            vwap_trend=True,
        )
    )
    return IndicatorsResponse(ok=True, count_total=1, returned=1, signals=[sample])


@router.get("/{symbol}", response_model=IndicatorsResponse, operation_id="getIndicatorsSymbol")
async def get_indicators_symbol(
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    timeframe: str = Query("1h"),
    limit: int = Query(180, ge=50, le=500),
) -> IndicatorsResponse:
    try:
        df = _fetch_klines(symbol, timeframe, limit)
        ind = prepare_indicators_for_backtest(df)
        if ind.empty:
            return IndicatorsResponse(ok=False, count_total=1, returned=0, signals=[],
                                      error="no data")
        row = ind.iloc[-1].to_dict()
        sig = IndicatorSignal(
            symbol=symbol,
            timeframe=timeframe,
            indicators=IndicatorSet(**{k: float(v) for k, v in row.items() if isinstance(v, (int, float))})
        )
        return IndicatorsResponse(ok=True, count_total=1, returned=1, signals=[sig])
    except Exception as e:
        return IndicatorsResponse(ok=False, count_total=1, returned=0, signals=[],
                                  error=str(e))








