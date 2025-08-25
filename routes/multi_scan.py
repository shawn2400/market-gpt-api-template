# routes/multi_scan.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Request
from typing import List
import os, time
import pandas as pd
import requests
from pydantic import BaseModel, Field
from utils.indicators import prepare_indicators_for_backtest

# שימו לב: נשאיר את הייבוא הזה, אבל נשתמש בו רק אם include_ai=True
from utils.ai_analysis import analyze_with_ai

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
router = APIRouter(prefix="/scan", tags=["Scan"])

_rate_state = {}
def _rl(ip: str, limit=30, window=60):
    now = time.time()
    calls = [c for c in _rate_state.get(ip, []) if now - c < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rate_state[ip] = calls
    return True

def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    r = requests.get(
        url,
        params={"symbol": symbol.upper(), "interval": interval, "limit": int(limit)},
        timeout=10,
    )
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

class IndicatorSet(BaseModel):
    rsi: float | None = None
    ema_21: float | None = None
    adx: float | None = None
    atr: float | None = None
    vwap_trend: bool | None = None

class ScanSignal(BaseModel):
    symbol: str
    interval: str
    indicators: IndicatorSet | None = None
    analysis: str | None = None
    ok: bool = True
    error: str | None = None

class MultiScanResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    signals: List[ScanSignal] = Field(default_factory=list)
    error: str | None = None

@router.get("/", response_model=MultiScanResponse)
async def scan_symbols(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=200),
    include_ai: bool = Query(False, description="If true, also run lightweight AI commentary"),
    request: Request = None
) -> MultiScanResponse:
    if not _rl(request.client.host):
        raise HTTPException(429, "Rate limit exceeded")

    out: List[ScanSignal] = []
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    for s in syms:
        try:
            df = _fetch_klines(s, interval, limit)
            if df.empty:
                out.append(ScanSignal(symbol=s, interval=interval, ok=False, error="no data"))
                continue
            ind = prepare_indicators_for_backtest(df)
            row = ind.iloc[-1].to_dict()

            ai_txt = None
            if include_ai:
                try:
                    # מעבירים רק תקציר – commentary קצר, כדי לא להכביד
                    ai_txt = await analyze_with_ai({"symbol": s, "rsi": row.get("rsi"), "adx": row.get("adx"), "ema_21": row.get("ema_21")})
                except Exception as e:
                    ai_txt = f"(ai failed: {e})"

            out.append(ScanSignal(symbol=s, interval=interval, indicators=IndicatorSet(**row), analysis=ai_txt))
        except Exception as e:
            out.append(ScanSignal(symbol=s, interval=interval, ok=False, error=str(e)))

    return MultiScanResponse(ok=True, count_total=len(syms), returned=len(out), signals=out)




































































