# routes/context.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Tuple
import os, time, math, asyncio
import pandas as pd
import httpx

# אבטחה (Fallback אם אין utils.auth)
try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.indicators import (
    rsi as rsi_fn, adx as adx_fn, atr as atr_fn, ema as ema_fn, bollinger_bands
)
from utils.watchlist_utils import load_watchlist

router = APIRouter(prefix="", tags=["Context"], dependencies=[Depends(require_bearer_token)])

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
CTX_CACHE_TTL = int(os.getenv("CONTEXT_TTL_SECONDS", "20"))
MAX_LIMIT = 200

# פרמטרים לכיוונון דגלים (ENV)
BREAKOUT_WINDOW = int(os.getenv("BREAKOUT_WINDOW", "50"))
EMA_CROSS_LOOKBACK = int(os.getenv("EMA_CROSS_LOOKBACK", "2"))
ATR_MULT_STOP = float(os.getenv("ATR_MULT_STOP", "1.5"))
ADX_TREND_MIN = float(os.getenv("ADX_TREND_MIN", "20.0"))
RSI_OB = float(os.getenv("RSI_OB", "70.0"))
RSI_OS = float(os.getenv("RSI_OS", "30.0"))
BB_BW_THR = float(os.getenv("BB_BW_THR", "0.02"))  # bandwidth יחסי ל-mid
ATR_PCT_LOW = float(os.getenv("ATR_PCT_LOW", "0.5"))
ATR_PCT_HIGH = float(os.getenv("ATR_PCT_HIGH", "1.2"))

_cache: Dict[str, Tuple[float, dict]] = {}
_rate: Dict[str, List[float]] = {}

def _now() -> float: return time.time()

def _rl(ip: str, limit=60, window=60) -> bool:
    now = _now()
    calls = [t for t in _rate.get(ip, []) if now - t < window]
    if len(calls) >= limit: return False
    calls.append(now)
    _rate[ip] = calls
    return True

def _in_cache(key: str) -> Optional[dict]:
    item = _cache.get(key)
    if not item: return None
    ts, data = item
    if (_now() - ts) <= CTX_CACHE_TTL:
        return data
    return None

def _save_cache(key: str, data: dict) -> None:
    _cache[key] = (_now(), data)

async def _fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        arr = r.json()
    if not arr:
        return pd.DataFrame()
    cols = ["open_time","open","high","low","close","volume","close_time","qv","nTrades","taker_base","taker_quote","x"]
    df = pd.DataFrame(arr, columns=cols[:len(arr[0])])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open","high","low","close","volume"]]

def _obv_z(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty: return pd.Series(dtype=float)
    close = pd.to_numeric(df["close"], errors="coerce")
    vol = pd.to_numeric(df["volume"], errors="coerce")
    direction = close.diff().fillna(0.0).apply(lambda x: 1 if x>0 else (-1 if x<0 else 0))
    obv = (direction * vol).cumsum()
    w = 50
    roll_mean = obv.rolling(w, min_periods=max(10, min(20, len(obv)))).mean()
    roll_std  = obv.rolling(w, min_periods=max(10, min(20, len(obv)))).std()
    z = (obv - roll_mean) / roll_std.replace(0.0, pd.NA)
    return z.fillna(0.0)

class ContextOut(BaseModel):
    symbol: str
    interval: str
    price: float
    rsi: float | None = None
    adx: float | None = None
    atr: float | None = None
    ema_21: float | None = None
    ema_50: float | None = None
    bb_mid: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    obv_z: float | None = None
    vol_15m_est: float | None = None
    filters: Dict[str, Any] = {}
    ts: int

class BatchOut(BaseModel):
    count: int
    items: List[Dict[str, Any]]   # תומך גם ב-full וגם ב-compact
    errors: Dict[str, str] = {}

def _last(s: pd.Series) -> Optional[float]:
    try:
        v = float(s.dropna().iloc[-1])
        if math.isfinite(v): return round(v, 6)
        return None
    except Exception:
        return None

def _anchor_hint() -> str:
    try:
        wl = load_watchlist()
        btc = next((it for it in wl if str(it.get("symbol","")).upper()=="BTCUSDT"), None)
        if btc:
            return "BULLISH" if str(btc.get("direction","")).upper()=="LONG" else "BEARISH"
    except Exception:
        pass
    return "NEUTRAL"

async def compute_context(symbol: str, interval: str, limit: int, include_filters: bool) -> ContextOut:
    key = f"{symbol.upper()}|{interval}|{limit}|{int(include_filters)}"
    cached = _in_cache(key)
    if cached:
        return ContextOut(**cached)

    df = await _fetch_klines(symbol, interval, limit)
    if df.empty:
        raise HTTPException(404, f"no data for {symbol}")

    close = pd.to_numeric(df["close"], errors="coerce")
    high  = pd.to_numeric(df["high"], errors="coerce")
    low   = pd.to_numeric(df["low"], errors="coerce")
    vol   = pd.to_numeric(df["volume"], errors="coerce")
    price = float(close.iloc[-1])

    rsi_s  = rsi_fn(close, 14)
    adx_s  = adx_fn(df, 14)
    atr_s  = atr_fn(df, 14)
    ema21  = ema_fn(close, 21)
    ema50  = ema_fn(close, 50)
    bb_mid_s, bb_up_s, bb_lo_s = bollinger_bands(close, period=20, std_factor=2.0)
    obv_zs = _obv_z(df)

    diffs = close.diff().abs().dropna()
    vol_15m_est = float(diffs.tail(20).mean() or 0.0) if not diffs.empty else None

    data = {
        "symbol": symbol.upper(),
        "interval": interval,
        "price": round(price, 6),
        "rsi": _last(rsi_s),
        "adx": _last(adx_s),
        "atr": _last(atr_s),
        "ema_21": _last(ema21),
        "ema_50": _last(ema50),
        "bb_mid": _last(bb_mid_s),
        "bb_upper": _last(bb_up_s),
        "bb_lower": _last(bb_lo_s),
        "obv_z": _last(obv_zs),
        "vol_15m_est": (round(vol_15m_est, 6) if vol_15m_est is not None else None),
        "filters": {},
        "ts": int(_now()),
    }

    if include_filters:
        rsi_v   = data["rsi"] or 0.0
        adx_v   = data["adx"] or 0.0
        atr_v   = data["atr"] or 0.0
        ema21_v = data["ema_21"] or price
        ema50_v = data["ema_50"] or price
        bbm     = data["bb_mid"]
        bbu     = data["bb_upper"]
        bbl     = data["bb_lower"]
        obvz    = data["obv_z"] or 0.0

        trending_up   = (price > ema21_v) and (ema21_v > ema50_v) and (adx_v >= ADX_TREND_MIN)
        trending_down = (price < ema21_v) and (ema21_v < ema50_v) and (adx_v >= ADX_TREND_MIN)

        overbought = rsi_v >= RSI_OB
        oversold   = rsi_v <= RSI_OS

        v_ma = float(vol.rolling(30, min_periods=15).mean().iloc[-1] or 0.0)
        v_spike = (float(vol.iloc[-1]) / v_ma >= 2.0) if v_ma > 0 else False

        ema21_prev = float(ema21.iloc[-EMA_CROSS_LOOKBACK]) if len(ema21) > EMA_CROSS_LOOKBACK else ema21_v
        ema50_prev = float(ema50.iloc[-EMA_CROSS_LOOKBACK]) if len(ema50) > EMA_CROSS_LOOKBACK else ema50_v
        ema_cross_bull = (ema21_prev <= ema50_prev) and (ema21_v > ema50_v)
        ema_cross_bear = (ema21_prev >= ema50_prev) and (ema21_v < ema50_v)

        win = min(BREAKOUT_WINDOW, len(high)-1) if len(high) > 1 else 1
        prev_max = float(high.iloc[-win-1:-1].max()) if win >= 2 else float(high.iloc[-2])
        prev_min = float(low .iloc[-win-1:-1].min()) if win >= 2 else float(low .iloc[-2])
        breakout_up   = price > prev_max
        breakout_down = price < prev_min

        atr_pct = (atr_v / price * 100.0) if price > 0 and atr_v > 0 else None
        vol_regime = "low"
        if atr_pct is not None:
            if atr_pct >= ATR_PCT_HIGH: vol_regime = "high"
            elif atr_pct >= ATR_PCT_LOW: vol_regime = "mid"

        bb_bw = None
        danger_chop = False
        if bbm and bbu and bbl and bbm != 0:
            bb_bw = (bbu - bbl) / abs(bbm)
            near_mid = abs(price - bbm)/price <= 0.002
            danger_chop = (adx_v < 18.0) and (bb_bw <= BB_BW_THR) and near_mid

        risk_stop = atr_v * ATR_MULT_STOP if atr_v else None
        rr_up = rr_down = None
        if risk_stop and risk_stop > 0:
            tgt_up = None
            if bbu: tgt_up = bbu
            tgt_up = max(tgt_up or 0.0, prev_max) if prev_max else (tgt_up or None)
            if tgt_up and tgt_up > price:
                rr_up = (tgt_up - price) / risk_stop
            tgt_dn = None
            if bbl: tgt_dn = bbl
            tgt_dn = min(tgt_dn or 1e20, prev_min) if prev_min else (tgt_dn or None)
            if tgt_dn and tgt_dn < price:
                rr_down = (price - tgt_dn) / risk_stop
        rr_baseline = None
        if rr_up and rr_down: rr_baseline = max(rr_up, rr_down)
        elif rr_up: rr_baseline = rr_up
        elif rr_down: rr_baseline = rr_down

        anchor_hint = _anchor_hint()

        score = 0.0
        score += 1.5 if trending_up else 0.0
        score -= 1.0 if trending_down else 0.0
        score += 1.0 if v_spike else 0.0
        score += 0.6 if (rr_baseline and rr_baseline >= 1.5) else 0.0
        score += 1.2 if (rr_baseline and rr_baseline >= 2.0) else 0.0
        score += 0.4 if obvz >= 1.0 else 0.0
        score -= 0.5 if overbought else 0.0
        score -= 0.4 if oversold else 0.0
        score -= 0.8 if danger_chop else 0.0
        if anchor_hint == "BULLISH" and trending_up: score += 0.3
        if anchor_hint == "BEARISH" and trending_down: score += 0.3

        data["filters"] = {
            "trending_up": trending_up,
            "trending_down": trending_down,
            "overbought": overbought,
            "oversold": oversold,
            "volume_spike": v_spike,
            "ema_cross_bull": ema_cross_bull,
            "ema_cross_bear": ema_cross_bear,
            "is_breakout_up": breakout_up,
            "is_breakout_down": breakout_down,
            "atr_pct": (round(atr_pct, 3) if atr_pct is not None else None),
            "atr_stop_x": ATR_MULT_STOP,
            "bb_bandwidth": (round(bb_bw, 4) if bb_bw is not None else None),
            "danger_chop": danger_chop,
            "rr_up": (round(rr_up, 3) if rr_up is not None else None),
            "rr_down": (round(rr_down, 3) if rr_down is not None else None),
            "rr_baseline": (round(rr_baseline, 3) if rr_baseline is not None else None),
            "vol_regime": vol_regime,
            "anchor_hint": anchor_hint,
            "score_light": round(score, 3),
        }

    _save_cache(key, data)
    return ContextOut(**data)

@router.get("/context", response_model=ContextOut)
async def get_context(
    request: Request,
    symbol: str = Query(..., min_length=5, max_length=20),
    interval: str = Query("15m"),
    limit: int = Query(120, ge=60, le=MAX_LIMIT),
    include_filters: bool = Query(True),
):
    if not _rl(request.client.host):
        raise HTTPException(429, "Rate limit exceeded")
    return await compute_context(symbol, interval, limit, include_filters)

class BatchCompactItem(BaseModel):
    symbol: str
    price: float
    score_light: float | None = None
    rr_baseline: float | None = None

@router.get("/context/batch", response_model=BatchOut)
async def get_context_batch(
    request: Request,
    symbols: Optional[str] = Query(None, description="Comma-separated; אם ריק נלקח מה-Watchlist"),
    interval: str = Query("15m"),
    limit: int = Query(120, ge=60, le=MAX_LIMIT),
    include_filters: bool = Query(True),
    k: Optional[int] = Query(None, ge=1, le=100, description="אופציונלי: K ראשונים לפי score_light"),
    compact: bool = Query(False, description="החזר קומפקטי: symbol, price, score_light, rr_baseline"),
):
    if not _rl(request.client.host):
        raise HTTPException(429, "Rate limit exceeded")

    if symbols:
        pool = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        wl = load_watchlist()
        pool = [str(it["symbol"]).upper() for it in wl if it.get("symbol")]
        if "BTCUSDT" not in pool:
            pool.insert(0, "BTCUSDT")
    if not pool:
        raise HTTPException(400, "no symbols")

    results: List[ContextOut] = []
    errors: Dict[str, str] = {}

    async def one(sym: str):
        nonlocal results, errors
        try:
            ctx = await compute_context(sym, interval, limit, include_filters)
            results.append(ctx)
        except Exception as e:
            errors[sym] = str(e)

    await asyncio.gather(*[one(s) for s in pool])

    # מיון לפי score_light אם יש וצריך K
    if k is not None and include_filters:
        results.sort(key=lambda c: ((c.filters or {}).get("score_light", 0.0)), reverse=True)
        results = results[:k]

    if compact:
        items = []
        for c in results:
            f = c.filters or {}
            items.append(BatchCompactItem(
                symbol=c.symbol,
                price=c.price,
                score_light=float(f.get("score_light")) if f.get("score_light") is not None else None,
                rr_baseline=float(f.get("rr_baseline")) if f.get("rr_baseline") is not None else None,
            ).model_dump())
        return BatchOut(count=len(items), items=items, errors=errors)

    # full
    return BatchOut(count=len(results), items=[c.model_dump() for c in results], errors=errors)


