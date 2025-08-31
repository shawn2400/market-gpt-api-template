# routes/context.py
from __future__ import annotations

import os
from typing import Dict, Any, List, Optional, Literal

from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.watchlist_utils import is_top10
from utils.hours_profile import hours_profile_now
from utils.scanner_utils import fetch_ohlcv

try:
    # אופציונלי: אם קיים Mod funding – ניקח ממנו ביאס [-1..+1] (חיובי=תומך LONG)
    from utils.funding_bias import funding_bias_for_symbol  # should return float in [-1, 1]
except Exception:  # soft fallback
    def funding_bias_for_symbol(symbol: str) -> float:
        return 0.0


router = APIRouter(prefix="/context", tags=["Context"], dependencies=[Depends(require_api_key)])

Interval = Literal["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d"]

MIN_RR_TOP10 = float(os.getenv("MIN_RR_TOP10", "1.6"))
MIN_RR_ALT   = float(os.getenv("MIN_RR_ALT", "1.9"))

# ------------------------- Models -------------------------

class ContextItem(BaseModel):
    symbol: str
    price: Optional[float] = None
    indicators: Dict[str, Any] = {}
    filters: Dict[str, Any] = {}

class BatchIn(BaseModel):
    symbols: List[str] = Field(..., description="Symbols like BTCUSDT,ETHUSDT")
    interval: Interval = Field("15m")
    compact: bool = Field(True)

class BatchOut(BaseModel):
    interval: str
    items: List[ContextItem]

# ------------------------- Helpers -------------------------

def _vol_regime(atr_pct: float) -> str:
    # ~rule-of-thumb: ATR% over last 14 bars מול price
    if atr_pct >= 2.0:
        return "high"
    if atr_pct <= 0.8:
        return "low"
    return "mid"

def _ema_flags(ema21: float, ema50: float, prev_ema21: float, prev_ema50: float) -> Dict[str, Any]:
    trending_up = ema21 > ema50
    trending_down = ema50 > ema21
    cross = "none"
    if prev_ema21 <= prev_ema50 and ema21 > ema50:
        cross = "golden"
    elif prev_ema21 >= prev_ema50 and ema21 < ema50:
        cross = "death"
    return {
        "trending_up": trending_up,
        "trending_down": trending_down,
        "ema_cross": cross,
    }

def _breakout_flags(close_series, lookback: int = 20) -> Dict[str, Any]:
    try:
        prev = close_series.iloc[-(lookback+1):-1]
        last = float(close_series.iloc[-1])
        mx, mn = float(prev.max()), float(prev.min())
        return {
            "is_breakout": bool(last > mx or last < mn),
            "breakout_side": ("UP" if last > mx else ("DOWN" if last < mn else "NONE")),
            "range_prev": (mx - mn) / mn * 100.0 if mn else None,
        }
    except Exception:
        return {"is_breakout": False, "breakout_side": "NONE", "range_prev": None}

def _danger_chop(adx: float, rsi: float, ema21: float, ema50: float, close: float) -> bool:
    try:
        # אזור "שקט/צד" אופייני: ADX < 15 ואיזון RSI קרוב ל-50, וגם מחיר צמוד לממוצעים
        ema_mid = (ema21 + ema50) / 2.0
        proximity = abs(close - ema_mid) / close * 100.0
        return (adx < 15.0 and abs(rsi - 50.0) < 5.0 and proximity < 0.35)
    except Exception:
        return False

def _rr_min_for_symbol(symbol: str) -> float:
    return MIN_RR_TOP10 if is_top10(symbol) else MIN_RR_ALT

# ------------------------- Core -------------------------

async def _compute_context_for_symbol(symbol: str, interval: str = "15m") -> ContextItem:
    s = symbol.upper().strip()
    df = await fetch_ohlcv(s, interval=interval, limit=180)  # uses Binance futures endpoint
    if df is None or len(df) < 60:
        return ContextItem(symbol=s, price=None, indicators={}, filters={})

    # אינדיקטורים בסיסיים (כבר קיימים ב-DF מפונק' fetch?—נחשב כאן):
    import pandas as pd
    from ta.momentum import RSIIndicator
    from ta.trend import EMAIndicator, ADXIndicator
    from ta.volatility import AverageTrueRange

    close = df["close"]
    high = df["high"]
    low  = df["low"]

    rsi = RSIIndicator(close=close, window=14).rsi()
    ema21 = EMAIndicator(close=close, window=21).ema_indicator()
    ema50 = EMAIndicator(close=close, window=50).ema_indicator()
    adx = ADXIndicator(high=high, low=low, close=close, window=14).adx()
    atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    price = float(close.iloc[-1])
    last = {
        "rsi": float(rsi.iloc[-1]),
        "ema21": float(ema21.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "adx": float(adx.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "close": price,
    }
    prev = {
        "ema21": float(ema21.iloc[-2]),
        "ema50": float(ema50.iloc[-2]),
    }

    atr_pct = (last["atr"] / price * 100.0) if price else None
    vol_reg = _vol_regime(atr_pct or 0.0)

    ema_flags = _ema_flags(last["ema21"], last["ema50"], prev["ema21"], prev["ema50"])
    bo_flags = _breakout_flags(close, 20)

    rr_base = _rr_min_for_symbol(s)
    rr_bonus = float(hours_profile_now().get("rr_bonus", 0.0))

    funding_bias = funding_bias_for_symbol(s)  # [-1..+1]; 0 means neutral
    # בונוס קטן ברמת ה-MinRR (כשיש ביאס תומך LONG חיובי או SHORT שלילי)
    # שים לב: זה רק רמז, הוורקר יטפל בהתניות בפועל
    rr_bias_adj = -0.1 * abs(funding_bias)  # bias תומך → אפשר טיפה לרכך RR מ- baseline

    filters = {
        "vol_regime": vol_reg,
        **ema_flags,
        **bo_flags,
        "danger_chop": _danger_chop(last["adx"], last["rsi"], last["ema21"], last["ema50"], price),
        "rr_baseline": rr_base,
        "rr_bonus": rr_bonus,
        "min_rr": max(1.0, rr_base + rr_bonus + rr_bias_adj),
        "funding_bias": funding_bias,
    }

    indicators = {
        **last,
        "atr_pct": atr_pct,
    }

    return ContextItem(symbol=s, price=price, indicators=indicators, filters=filters)

# ------------------------- Routes -------------------------

@router.get("", response_model=ContextItem)
async def get_context(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: Interval = Query("15m"),
    compact: bool = Query(True),
):
    item = await _compute_context_for_symbol(symbol, interval)
    if compact:
        return ContextItem(symbol=item.symbol, price=item.price, filters=item.filters)
    return item

@router.post("/batch", response_model=BatchOut)
async def get_context_batch(payload: BatchIn = Body(...)):
    out: List[ContextItem] = []
    # הרצה סדורה, אפשר גם להאיץ עם gather אם תרצה
    for s in payload.symbols:
        try:
            item = await _compute_context_for_symbol(s, payload.interval)
        except Exception:
            item = ContextItem(symbol=s.upper(), price=None, indicators={}, filters={})
        if payload.compact:
            item = ContextItem(symbol=item.symbol, price=item.price, filters=item.filters)
        out.append(item)
    return BatchOut(interval=payload.interval, items=out)







