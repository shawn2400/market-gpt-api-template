from __future__ import annotations
import os
from typing import Dict, Any, List
import numpy as np
import pandas as pd
import httpx
from fastapi import APIRouter, Depends, Query
from utils.auth import require_bearer_token

router = APIRouter(prefix="/ai", tags=["AI"], dependencies=[Depends(require_bearer_token)])

_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1.0)
    out = np.empty_like(arr, dtype=float); out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out

def _rma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(arr, dtype=float)
    out[0] = np.nanmean(arr[:period]) if period <= len(arr) else arr[0]
    alpha = 1.0 / period
    for i in range(1, len(arr)):
        out[i] = (out[i - 1] * (1 - alpha)) + alpha * arr[i]
    return out

def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.diff(close, prepend=close[0])
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    avg_gain = _rma(gain, period); avg_loss = _rma(loss, period)
    rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))

def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev_close = np.roll(close, 1); prev_close[0] = close[0]
    tr = np.maximum.reduce([high - low, np.abs(high - prev_close), np.abs(low - prev_close)])
    return _rma(tr, period)

def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    up = high[1:] - high[:-1]; down = low[:-1] - low[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = _atr(high, low, close, period)
    plus_dm = np.concatenate([[0.0], plus_dm]); minus_dm = np.concatenate([[0.0], minus_dm])
    plus_r = _rma(plus_dm, period); minus_r = _rma(minus_dm, period)
    plus_di = 100.0 * np.where(tr == 0, 0.0, plus_r / tr)
    minus_di = 100.0 * np.where(tr == 0, 0.0, minus_r / tr)
    dx = 100.0 * np.where((plus_di + minus_di) == 0, 0.0, np.abs(plus_di - minus_di) / (plus_di + minus_di))
    return _rma(dx, period)

async def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> List[List[Any]]:
    url = f"{_FAPI}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params=params); r.raise_for_status()
        data = r.json()
        if not isinstance(data, list): raise RuntimeError("unexpected klines shape")
        return data

def _frame_to_df(rows: List[List[Any]]) -> pd.DataFrame:
    cols = ["ts","open","high","low","close","volume","close_ts","qv","trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna().reset_index(drop=True)

def _analyze(df: pd.DataFrame, interval: str) -> Dict[str, Any]:
    close = df["close"].to_numpy(float); high = df["high"].to_numpy(float); low = df["low"].to_numpy(float)
    rsi_last = float(_rsi(close, 14)[-1]); ema21 = float(_ema(close, 21)[-1]); ema50 = float(_ema(close, 50)[-1])
    atr_last = float(_atr(high, low, close, 14)[-1]); adx_last = float(_adx(high, low, close, 14)[-1]); c = float(close[-1])
    trend = "UP" if ema21 >= ema50 else "DOWN"
    direction, note = (None, None)
    if adx_last >= 20:
        if c >= ema21 >= ema50: direction, note = "LONG", "EMA21>=EMA50 & ADX>=20"
        elif c <= ema21 <= ema50: direction, note = "SHORT", "EMA21<=EMA50 & ADX>=20"
        else: note = "lite (structure mixed)"
    else:
        note = "lite (ADX<20)"
    quality = 6.5 + min(3.0, max(0.0, (adx_last - 20.0) * 0.1)) if direction else 5.0
    return {
        "market":"futures","interval":interval,"frames":[interval],"trend":trend,"direction":direction,
        "rsi":round(rsi_last,2),"adx":round(adx_last,2),"volume":float(df["volume"].iloc[-1]),
        "quality_score":round(float(quality),2),
        "signal":"BUY" if direction=="LONG" else ("SELL" if direction=="SHORT" else "HOLD"),
        "confidence": int(min(100, max(0, (quality/10.0)*100))),
        "reason":note,"close":c,"atr":round(atr_last,6),
    }

@router.get("/manual-scan", operation_id="getAiManualScan")
async def ai_manual_scan(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=1500),
) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    rows = await _fetch_klines(symbol, interval=interval, limit=limit)
    df = _frame_to_df(rows)
    if len(df) < 60:
        return {"symbol": symbol, "results": {"symbol": symbol, "market": "futures", "interval": interval, "signal": "HOLD", "reason": "lite (not enough data)"}}
    res = _analyze(df, interval); res["symbol"] = symbol
    return {"symbol": symbol, "results": res}







