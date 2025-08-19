# routes/ai_analyze.py
from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import math
import os

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from binance import Client

from utils.auth import require_bearer_token

# ========= Helpers =========
def _get_client() -> Client:
    return Client(
        api_key=os.getenv("BINANCE_API_KEY") or "",
        api_secret=os.getenv("BINANCE_API_SECRET") or ""
    )

def _fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """
    מנסה Futures klines ואם נכשל – חוזר ל-spot klines.
    """
    client = _get_client()
    data: Optional[List[List[Any]]] = None
    try:
        data = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception:
        data = client.get_klines(symbol=symbol, interval=interval, limit=limit)

    if not data:
        raise RuntimeError("no klines returned")

    # פורמט Binance:
    # [ open_time, open, high, low, close, volume, close_time, qav, trades, ... ]
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","taker_base","taker_quote","ignore"
    ])
    for col in ("open","high","low","close","volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df[["time","open","high","low","close","volume"]].reset_index(drop=True)

def _compute_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    מחשב RSI/ADX/ATR + EMA מהירים/איטיים. אם ta אינו מותקן — fallback מינימלי.
    """
    try:
        from ta.momentum import RSIIndicator
        from ta.trend import ADXIndicator, EMAIndicator
        from ta.volatility import AverageTrueRange

        rsi = RSIIndicator(close=df["close"], window=14, fillna=True).rsi().iloc[-1]
        adx = ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True
        ).adx().iloc[-1]
        atr = AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True
        ).average_true_range().iloc[-1]

        ema_fast = EMAIndicator(close=df["close"], window=21, fillna=True).ema_indicator().iloc[-1]
        ema_slow = EMAIndicator(close=df["close"], window=50, fillna=True).ema_indicator().iloc[-1]

        trend = "bull" if ema_fast > ema_slow else ("bear" if ema_fast < ema_slow else "flat")
        return {"rsi": float(rsi), "adx": float(adx), "atr": float(atr),
                "ema_fast": float(ema_fast), "ema_slow": float(ema_slow), "trend": trend, "fallback": False}
    except Exception:
        # Fallback: חישוב מינימלי בלי ta
        close = df["close"].values
        high  = df["high"].values
        low   = df["low"].values

        # RSI פשטני
        gains = []
        losses = []
        for i in range(1, min(15, len(close))):
            ch = close[-i] - close[-i-1]
            gains.append(max(0.0, ch))
            losses.append(max(0.0, -ch))
        avg_gain = (sum(gains) / len(gains)) if gains else 0.0
        avg_loss = (sum(losses) / len(losses)) if losses else 1e-9
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # ATR פשטני
        trs = []
        for i in range(1, min(15, len(close))):
            tr = max(high[-i] - low[-i],
                     abs(high[-i] - close[-i-1]),
                     abs(low[-i] - close[-i-1]))
            trs.append(tr)
        atr = (sum(trs) / len(trs)) if trs else 0.0

        # EMA פשטני
        def _ema(series: List[float], window: int) -> float:
            if not series:
                return math.nan
            k = 2/(window+1)
            ema_val = series[0]
            for v in series[1:]:
                ema_val = v*k + ema_val*(1-k)
            return ema_val
        ema_fast = _ema(list(close[-50:]), 21)
        ema_slow = _ema(list(close[-100:]), 50)
        trend = "bull" if ema_fast > ema_slow else ("bear" if ema_fast < ema_slow else "flat")

        # ADX לא מחושב כאן — נחזיר 20 ניטרלי
        adx = 20.0

        return {"rsi": float(rsi), "adx": float(adx), "atr": float(atr),
                "ema_fast": float(ema_fast), "ema_slow": float(ema_slow), "trend": trend, "fallback": True}

def _decision(ind: Dict[str, Any]) -> Dict[str, Any]:
    rsi = ind["rsi"]; adx = ind["adx"]; trend = ind["trend"]
    signal = None
    reason = []
    if trend == "bull" and rsi >= 55 and adx >= 18:
        signal = "LONG"; reason.append("bull+RSI>=55+ADX>=18")
    elif trend == "bear" and rsi <= 45 and adx >= 18:
        signal = "SHORT"; reason.append("bear+RSI<=45+ADX>=18")
    else:
        reason.append("no-setup")

    # ניקוד 0..10
    score = 0.0
    if signal:
        score += min(4.0, max(0.0, (adx-18)/12*4))  # חוזק מגמה
        score += min(3.0, max(0.0, (abs(rsi-50))/25*3))  # סטייה מ-50
        score += 3.0 if (trend == "bull" and signal=="LONG") or (trend=="bear" and signal=="SHORT") else 0.0
    conf = min(1.0, score/10.0)

    return {"signal": signal, "quality_score": round(score, 2),
            "confidence": round(conf, 2), "reason": "+".join(reason) }

# ========= Router =========
router = APIRouter(prefix="/ai", tags=["AI"], dependencies=[Depends(require_bearer_token)])

@router.get("/manual-scan", summary="AI Manual Scan for a symbol (RSI/ADX/ATR/EMA)")
def manual_scan(
    symbol: str = Query(..., min_length=5, max_length=20),
    interval: str = Query("15m"),
    limit: int = Query(200, ge=50, le=1000),
) -> Dict[str, Any]:
    """
    מנתח סימבול יחיד לפי נרות Binance ומחזיר מדדים + אות אפשרי.
    """
    try:
        df = _fetch_klines(symbol=symbol.upper(), interval=interval, limit=limit)
        ind = _compute_indicators(df)
        dec = _decision(ind)

        last = df.iloc[-1].to_dict()
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "market": "futures",
            "interval": interval,
            "frames": [interval],
            "trend": ind["trend"],
            "direction": "UP" if ind["trend"]=="bull" else ("DOWN" if ind["trend"]=="bear" else None),
            "rsi": ind["rsi"],
            "adx": ind["adx"],
            "atr": ind["atr"],
            "ema_fast": ind["ema_fast"],
            "ema_slow": ind["ema_slow"],
            "volume": float(df["volume"].iloc[-1]),
            "close": float(df["close"].iloc[-1]),
            "quality_score": dec["quality_score"],
            "signal": dec["signal"],
            "confidence": dec["confidence"],
            "reason": dec["reason"] if not ind.get("fallback") else f"{dec['reason']} (fallback-no-ta)",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"analyze-error: {exc}")





