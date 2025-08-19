# routes/ai_analyze.py
from __future__ import annotations
import os
from typing import Dict, Any, List
from fastapi import APIRouter, Query
import httpx, pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, ADXIndicator
from ta.volatility import AverageTrueRange

router = APIRouter(tags=["AI"])
_FAPI = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

async def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> List[List[Any]]:
    url = f"{_FAPI}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise RuntimeError("unexpected klines shape")
        return data

def _frame_to_df(rows: List[List[Any]]) -> pd.DataFrame:
    cols = ["ts","open","high","low","close","volume","close_ts","qv","trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna().reset_index(drop=True)

def _analyze(df: pd.DataFrame) -> Dict[str, Any]:
    rsi = RSIIndicator(close=df["close"], window=14).rsi().iloc[-1]
    adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14).adx().iloc[-1]
    ema_fast = EMAIndicator(close=df["close"], window=21).ema_indicator().iloc[-1]
    ema_slow = EMAIndicator(close=df["close"], window=50).ema_indicator().iloc[-1]
    atr = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range().iloc[-1]
    close = float(df["close"].iloc[-1])

    trend = "UP" if ema_fast >= ema_slow else "DOWN"
    direction = None
    note = None
    if adx >= 20:
        if close >= ema_fast >= ema_slow:
            direction, note = "LONG", "EMA21>=EMA50 & ADX>=20"
        elif close <= ema_fast <= ema_slow:
            direction, note = "SHORT", "EMA21<=EMA50 & ADX>=20"
    else:
        note = "lite (ADX<20) – no strong trend"

    quality = 5.0
    if direction:
        quality = 6.5 + min(3.0, max(0.0, (adx - 20.0) * 0.1))

    return {
        "frames": ["15m"],
        "trend": trend,
        "direction": direction,
        "rsi": float(rsi),
        "adx": float(adx),
        "volume": float(df["volume"].iloc[-1]),
        "quality_score": round(float(quality), 2),
        "signal": "BUY" if direction == "LONG" else ("SELL" if direction == "SHORT" else "HOLD"),
        "confidence": int(min(100, max(0, (quality/10.0)*100))),
        "reason": note,
        "close": close,
        "atr": float(atr),
    }

@router.get("/ai/manual-scan", operation_id="getAiManualScan")
async def ai_manual_scan(symbol: str = Query(..., description="e.g. BTCUSDT"),
                         interval: str = Query("15m"),
                         limit: int = Query(200, ge=50, le=1500)) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    try:
        rows = await _fetch_klines(symbol, interval=interval, limit=limit)
        df = _frame_to_df(rows)
        if len(df) < 60:
            return {"symbol": symbol, "results": {"signal": "HOLD", "reason": "lite (not enough data)"}}
        res = _analyze(df)
        return {"symbol": symbol, "results": res}
    except Exception as e:
        return {
            "symbol": symbol,
            "results": {
                "signal": "HOLD",
                "reason": f"lite (analyze-fallback: {type(e).__name__})",
                "frames": [interval],
                "trend": None, "direction": None,
                "rsi": None, "adx": None, "volume": None, "quality_score": None,
                "confidence": None, "close": None, "atr": None,
            }
        }




