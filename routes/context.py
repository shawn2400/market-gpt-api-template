# routes/context.py
from __future__ import annotations
from fastapi import APIRouter, Query, Body, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np
import requests
import os, time

from utils.indicators import prepare_indicators_for_backtest

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# ----- Router (תאימות לשני שמות) -----
router = APIRouter(tags=["Context"])
context_router = router  # למקרה שייבאת בעבר בשם הזה

# ----- Cache קצר כדי להפחית עומס -----
_CACHE: Dict[Tuple[str, str], Tuple[float, pd.DataFrame]] = {}
CACHE_TTL_SEC = int(os.getenv("CONTEXT_CACHE_TTL", "8"))

# ----- Fetch -----
def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    key = (symbol.upper(), interval)
    now = time.time()
    if key in _CACHE:
        ts, df_cached = _CACHE[key]
        if now - ts <= CACHE_TTL_SEC:
            return df_cached.copy()

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

    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","qv","nTrades","taker_base","taker_quote","x"
    ]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    _CACHE[key] = (now, df.copy())
    return df

# ----- Utils -----
def _clean_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    except Exception:
        return None

def _last2(series: pd.Series) -> Tuple[Optional[float], Optional[float]]:
    if series is None or series.empty:
        return None, None
    v1 = _clean_float(series.iloc[-1])
    v2 = _clean_float(series.iloc[-2]) if len(series) >= 2 else None
    return v1, v2

# ----- Filters -----
def _vol_regime_tag(ind: pd.DataFrame) -> str:
    price = _clean_float(ind["close"].iloc[-1])
    atr = _clean_float(ind["atr"].iloc[-1])
    if not price or not atr:
        return "mid"
    pct = (atr / price) * 100.0
    if pct < 1.2:
        return "low"
    if pct < 2.5:
        return "mid"
    return "high"

def _danger_chop_flag(ind: pd.DataFrame) -> bool:
    adx = _clean_float(ind["adx"].iloc[-1])
    mid = _clean_float(ind["bb_mid"].iloc[-1])
    up  = _clean_float(ind["bb_upper"].iloc[-1])
    lo  = _clean_float(ind["bb_lower"].iloc[-1])
    price = _clean_float(ind["close"].iloc[-1])
    if None in (adx, mid, up, lo, price):
        return False
    width = ((up - lo) / mid) if mid > 0 else 0.0
    near_mid = abs(price - mid) / mid if mid > 0 else 0.0
    return (adx < 18) and (width < 0.025) and (near_mid < 0.005)

def _volume_spike_flag(df_raw: pd.DataFrame) -> bool:
    if df_raw is None or df_raw.empty:
        return False
    vol = pd.to_numeric(df_raw["volume"], errors="coerce")
    if vol.isna().all():
        return False
    v_now = _clean_float(vol.iloc[-1])
    ma = _clean_float(vol.rolling(20, min_periods=5).mean().iloc[-1])
    if v_now is None or ma is None or ma == 0:
        return False
    return v_now >= 1.8 * ma

def _trend_flags(ind: pd.DataFrame) -> Dict[str, bool]:
    price, price_prev = _last2(ind["close"])
    ema21, ema21_prev = _last2(ind["ema_21"])
    ema50, ema50_prev = _last2(ind["ema_50"]) if "ema_50" in ind.columns else (None, None)
    adx, _ = _last2(ind["adx"])
    trending_up = bool(price and ema21 and ema50 and adx and price > ema21 > ema50 and adx >= 20)
    trending_down = bool(price and ema21 and ema50 and adx and price < ema21 < ema50 and adx >= 20)
    return {"trending_up": trending_up, "trending_down": trending_down}

def _ema_cross_flags(ind: pd.DataFrame) -> Dict[str, bool]:
    ema21, ema21_prev = _last2(ind["ema_21"])
    ema50, ema50_prev = _last2(ind["ema_50"]) if "ema_50" in ind.columns else (None, None)
    price, price_prev = _last2(ind["close"])

    cross_21_50_up = bool(ema21_prev is not None and ema50_prev is not None and ema21_prev < ema50_prev and ema21 > ema50)
    cross_21_50_dn = bool(ema21_prev is not None and ema50_prev is not None and ema21_prev > ema50_prev and ema21 < ema50)
    cross_price_21_up = bool(price_prev is not None and ema21_prev is not None and price_prev < ema21_prev and price > ema21)
    cross_price_21_dn = bool(price_prev is not None and ema21_prev is not None and price_prev > ema21_prev and price < ema21)

    return {
        "ema_cross_21_50_up": cross_21_50_up,
        "ema_cross_21_50_dn": cross_21_50_dn,
        "ema_cross_price_21_up": cross_price_21_up,
        "ema_cross_price_21_dn": cross_price_21_dn,
    }

def _breakout_flags(ind: pd.DataFrame) -> Dict[str, bool]:
    price, _ = _last2(ind["close"])
    up, _    = _last2(ind["bb_upper"])
    lo, _    = _last2(ind["bb_lower"])
    return {
        "is_breakout_up": bool(price is not None and up is not None and price > up),
        "is_breakout_down": bool(price is not None and lo is not None and price < lo),
    }

def _rr_baseline(ind: pd.DataFrame) -> Dict[str, Optional[float]]:
    """
    RR היפותטי:
      LONG: SL = price - 1.5*ATR, TP = min(bb_upper, price + 2*risk)
      SHORT: SL = price + 1.5*ATR, TP = max(bb_lower, price - 2*risk)
    """
    price = _clean_float(ind["close"].iloc[-1])
    atr   = _clean_float(ind["atr"].iloc[-1])
    up    = _clean_float(ind["bb_upper"].iloc[-1])
    lo    = _clean_float(ind["bb_lower"].iloc[-1])

    rr_long = None
    rr_short = None
    if price and atr and atr > 0:
        risk_l = 1.5 * atr
        tp_l = min(up, price + 2 * risk_l) if up is not None else price + 2 * risk_l
        reward_l = tp_l - price
        if risk_l > 0:
            rr_long = round(reward_l / risk_l, 2)

        risk_s = 1.5 * atr
        tp_s = max(lo, price - 2 * risk_s) if lo is not None else price - 2 * risk_s
        reward_s = price - tp_s
        if risk_s > 0:
            rr_short = round(reward_s / risk_s, 2)

    return {"rr_long": rr_long, "rr_short": rr_short}

def _score_light(ind: pd.DataFrame, flags: Dict[str, Any]) -> float:
    """
    ניקוד קל (0–10): טרנד, RR, ניתוק מדשדוש, ווליומים.
    """
    rr = _rr_baseline(ind)
    trending_bonus = 1.0 if (flags.get("trending_up") or flags.get("trending_down")) else 0.0
    rr_bonus = 0.0
    if rr["rr_long"] and rr["rr_long"] >= 1.8:
        rr_bonus += 1.0
    if rr["rr_short"] and rr["rr_short"] >= 1.8:
        rr_bonus += 1.0
    chop_pen = -1.0 if flags.get("danger_chop") else 0.0
    vol_bonus = 0.5 if flags.get("volume_spike") else 0.0

    score = 5.0 + trending_bonus + rr_bonus + chop_pen + vol_bonus
    return float(max(0.0, min(10.0, round(score, 2))))

# ----- Schemas -----
class CtxOut(BaseModel):
    symbol: str
    price: Optional[float] = None
    ind: Dict[str, Optional[float]] = Field(default_factory=dict)
    filters: Dict[str, Any] = Field(default_factory=dict)

class CtxBatchIn(BaseModel):
    symbols: List[str]
    interval: str = "15m"
    compact: bool = True

class CtxBatchOut(BaseModel):
    ok: bool = True
    items: List[CtxOut]

# ----- Builders -----
def _build_ind_snapshot(base: pd.DataFrame) -> Dict[str, Optional[float]]:
    row = base.iloc[-1]
    fields = ("rsi","adx","atr","ema_21","ema_50","bb_mid","bb_upper","bb_lower","macd_hist","close","volume")
    out: Dict[str, Optional[float]] = {}
    for f in fields:
        val = row.get(f) if f in row.index else None
        out[f] = _clean_float(val)
    # הסר close/volume מה-ind לרזולוציה קומפקטית (יש לנו price ו-volume_spike)
    out.pop("close", None)
    return out

def _compact_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    # מחזיר תת-סט קטן ורלוונטי
    keep = [
        "vol_regime","danger_chop","volume_spike",
        "trending_up","trending_down",
        "ema_cross_21_50_up","ema_cross_21_50_dn",
        "ema_cross_price_21_up","ema_cross_price_21_dn",
        "is_breakout_up","is_breakout_down",
        "rr_long","rr_short","score_light",
    ]
    return {k: filters.get(k) for k in keep}

# ----- Endpoints -----
@router.get("/context", response_model=CtxOut)
def context_single(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: str = Query("15m"),
    compact: bool = Query(True),
) -> CtxOut:
    df_raw = _fetch_klines(symbol, interval=interval, limit=200)
    if df_raw.empty:
        return CtxOut(symbol=symbol.upper(), price=None, ind={}, filters={})

    base = prepare_indicators_for_backtest(df_raw)
    if base.empty:
        return CtxOut(symbol=symbol.upper(), price=None, ind={}, filters={})

    price = _clean_float(base["close"].iloc[-1])

    # אינדיקטורים ופלגים
    ind = _build_ind_snapshot(base)
    flags: Dict[str, Any] = {}
    flags["vol_regime"] = _vol_regime_tag(base)
    flags["danger_chop"] = _danger_chop_flag(base)
    flags.update(_trend_flags(base))
    flags.update(_ema_cross_flags(base))
    flags.update(_breakout_flags(base))
    flags["volume_spike"] = _volume_spike_flag(df_raw)
    rr = _rr_baseline(base)
    flags.update(rr)
    flags["score_light"] = _score_light(base, {**flags})

    if compact:
        return CtxOut(symbol=symbol.upper(), price=price, ind={}, filters=_compact_filters(flags))

    return CtxOut(symbol=symbol.upper(), price=price, ind=ind, filters=flags)

@router.post("/context/batch", response_model=CtxBatchOut)
def context_batch(payload: CtxBatchIn = Body(...)) -> CtxBatchOut:
    if not payload.symbols:
        raise HTTPException(400, "symbols required")

    items: List[CtxOut] = []
    syms = [s.strip().upper() for s in payload.symbols if s and s.strip()]
    for s in syms:
        try:
            item = context_single(symbol=s, interval=payload.interval, compact=payload.compact)
            items.append(item)
        except Exception:
            items.append(CtxOut(symbol=s, price=None, ind={}, filters={}))
    return CtxBatchOut(ok=True, items=items)





