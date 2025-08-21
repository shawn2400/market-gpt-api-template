# routes/multi_scan.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import Dict, List, Optional
import os, requests, pandas as pd
from pydantic import BaseModel, Field

from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

router = APIRouter(prefix="/scan", tags=["Scan"])

# =====================
# Binance helpers
# =====================
def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
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

class ScanSignal(BaseModel):
    symbol: str
    interval: str
    indicators: Optional[IndicatorSet] = None
    ok: bool = True
    error: Optional[str] = None

class MultiScanResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    signals: List[ScanSignal] = Field(default_factory=list)
    error: Optional[str] = None

# =====================
# Endpoints
# =====================
@router.get("/info", response_model=MultiScanResponse, summary="Basic Scan Info")
async def scan_info(
    symbol: str = Query(..., description="Symbol e.g. BTCUSDT"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=200),
) -> MultiScanResponse:
    try:
        df = _fetch_klines(symbol, interval, limit)
        if df.empty:
            return MultiScanResponse(ok=False, count_total=1, returned=0, signals=[],
                                     error="no data")
        ind = prepare_indicators_for_backtest(df)
        row = ind.iloc[-1].to_dict()
        sig = ScanSignal(symbol=symbol, interval=interval, indicators=IndicatorSet(**row))
        return MultiScanResponse(ok=True, count_total=1, returned=1, signals=[sig])
    except Exception as e:
        return MultiScanResponse(ok=False, count_total=1, returned=0, signals=[],
                                 error=str(e))

@router.get("/", response_model=MultiScanResponse, summary="Multi-symbol scan")
async def scan_symbols(
    symbols: List[str] = Query(..., description="List of symbols e.g. BTCUSDT,ETHUSDT"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=200),
) -> MultiScanResponse:
    out: List[ScanSignal] = []
    for s in symbols:
        try:
            df = _fetch_klines(s, interval, limit)
            if df.empty:
                out.append(ScanSignal(symbol=s, interval=interval, ok=False, error="no data"))
                continue
            ind = prepare_indicators_for_backtest(df)
            row = ind.iloc[-1].to_dict()
            out.append(ScanSignal(symbol=s, interval=interval, indicators=IndicatorSet(**row)))
        except Exception as e:
            out.append(ScanSignal(symbol=s, interval=interval, ok=False, error=str(e)))

    return MultiScanResponse(ok=True, count_total=len(symbols), returned=len(out), signals=out)































































