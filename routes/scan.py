# routes/scan.py
from __future__ import annotations
import os
import math
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import numpy as np
import pandas as pd
from fastapi import APIRouter, Body, HTTPException, Query

# ---- לוגים ----
logger = logging.getLogger("algogpt.scan")

# ---- קונפיג ----
BINANCE_FUTURES_HTTP_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
DEFAULT_INTERVAL = os.getenv("DEFAULT_INTERVAL", "15m")
DEFAULT_LIMIT = int(os.getenv("SCAN_DEFAULT_LIMIT", "200"))

# ---- תלות אופציונלית: utils.top_volume ----
_top_symbols_func = None
try:
    from utils.top_volume import get_top_symbols as _get_top_symbols  # type: ignore
    _top_symbols_func = _get_top_symbols
except Exception as e:
    logger.warning("utils.top_volume.get_top_symbols not available (%s) — /scan/top-volume will synthesize BTC/ETH only.", e)

# ---- תלות אופציונלית: utils.indicators_ext (אם יש). אם אין — נשתמש ב-fallback מקומי. ----
try:
    from utils.indicators_ext import compute_indicators_ext as _compute_indicators_ext  # type: ignore
except Exception:
    _compute_indicators_ext = None

router = APIRouter()

# זיכרון תוצאות אחרונות ל-/scan GET
_LAST_SIGNALS: List[Dict[str, Any]] = []
_LAST_SCAN_OK: bool = True


# ===========================
# עזר: הורדת קנדלים מ-Binance
# ===========================
async def _fetch_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
    limit: int,
    http_base: str = BINANCE_FUTURES_HTTP_BASE,
) -> pd.DataFrame:
    url = f"{http_base}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": str(int(limit))}
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
        if r.status != 200:
            text = await r.text()
            raise HTTPException(status_code=502, detail=f"Binance klines error {r.status}: {text}")
        data = await r.json()

    if not isinstance(data, list) or not data:
        raise HTTPException(status_code=502, detail="Empty klines")
    # Binance columns order:
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
    ]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df


# ===========================
# אינדיקטורים בסיסיים
# ===========================
def _ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()

def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=window, min_periods=window).mean()

def _adx(df: pd.DataFrame, window: int = 14) -> pd.Series:
    # ADX פשוט (הערכה) לגיבוי מהיר
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = (high - high.shift(1)).clip(lower=0.0)
    minus_dm = (low.shift(1) - low).clip(lower=0.0)
    tr = _atr(df, window) * window  # שימוש ב-TR sum בקירוב
    plus_di = 100 * (plus_dm.rolling(window).sum() / tr)
    minus_di = 100 * (minus_dm.rolling(window).sum() / tr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(window).mean()
    return adx

def _supertrend(df: pd.DataFrame, period: int = 10, factor: float = 3.0) -> pd.Series:
    atr = _atr(df, window=period)
    hl2 = (df["high"] + df["low"]) / 2.0
    upper = hl2 + factor * atr
    lower = hl2 - factor * atr

    st = pd.Series(index=df.index, dtype=float)
    trend = pd.Series(index=df.index, dtype=int)  # +1 up, -1 down

    st.iloc[0] = upper.iloc[0]
    trend.iloc[0] = 1
    for i in range(1, len(df)):
        if df["close"].iloc[i] > st.iloc[i-1]:
            trend.iloc[i] = 1
        elif df["close"].iloc[i] < st.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]

        if trend.iloc[i] == 1:
            st.iloc[i] = min(upper.iloc[i], st.iloc[i-1])
        else:
            st.iloc[i] = max(lower.iloc[i], st.iloc[i-1])

    return trend  # +1/-1 מגמת סופרטרנד

def _ichimoku(df: pd.DataFrame, conv: int = 9, base: int = 26, span_b: int = 52) -> Dict[str, pd.Series]:
    high, low, close = df["high"], df["low"], df["close"]
    tenkan = (high.rolling(conv).max() + low.rolling(conv).min()) / 2.0
    kijun = (high.rolling(base).max() + low.rolling(base).min()) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(base)
    span_b_series = ((high.rolling(span_b).max() + low.rolling(span_b).min()) / 2.0).shift(base)
    chiko = close.shift(-base)
    return {"tenkan": tenkan, "kijun": kijun, "span_a": span_a, "span_b": span_b_series, "chiko": chiko}

def _stoch_rsi(close: pd.Series, window: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Tuple[pd.Series, pd.Series]:
    # חישוב RSI
    delta = close.diff()
    up = delta.clip(lower=0).rolling(window).mean()
    down = (-delta.clip(upper=0)).rolling(window).mean()
    rsi = 100 - (100 / (1 + (up / down.replace(0, np.nan))))
    # Stoch RSI
    rsi_min = rsi.rolling(window).min()
    rsi_max = rsi.rolling(window).max()
    stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    k = stoch_rsi.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return k, d

def _market_structure(df: pd.DataFrame, lookback: int = 5, pivot_span: int = 3) -> Dict[str, Any]:
    # זיהוי פיבוטים פשוט + קביעה HH/HL/LL/LH אחרון
    highs = df["high"]
    lows = df["low"]
    piv_high = highs[highs.rolling(pivot_span, center=True).max() == highs]
    piv_low = lows[lows.rolling(pivot_span, center=True).min() == lows]
    piv_high = piv_high.dropna().tail(lookback)
    piv_low = piv_low.dropna().tail(lookback)

    structure = None
    if len(piv_high) >= 2 and len(piv_low) >= 2:
        hh = piv_high.iloc[-1] > piv_high.iloc[-2]
        hl = piv_low.iloc[-1] > piv_low.iloc[-2]
        ll = piv_low.iloc[-1] < piv_low.iloc[-2]
        lh = piv_high.iloc[-1] < piv_high.iloc[-2]
        if hh and hl:
            structure = "HH-HL"
        elif lh and ll:
            structure = "LH-LL"
        elif hh and not hl:
            structure = "HH"
        elif ll and not lh:
            structure = "LL"

    return {
        "pivot_highs": float(piv_high.iloc[-1]) if len(piv_high) else None,
        "pivot_lows": float(piv_low.iloc[-1]) if len(piv_low) else None,
        "structure": structure,
    }


# ===========================
# ניקוד והסקת טרנד
# ===========================
def _score_signal(
    df: pd.DataFrame,
    ema_fast_len: int,
    ema_slow_len: int,
    adx_len: int,
    st_period: int,
    st_factor: float,
    ich_conv: int,
    ich_base: int,
    ich_span_b: int,
    ms_lookback: int,
    ms_pivot_span: int,
    min_adx: float,
) -> Tuple[Dict[str, Any], Optional[str], float]:
    close = df["close"]
    ema_fast = _ema(close, ema_fast_len)
    ema_slow = _ema(close, ema_slow_len)
    adx = _adx(df, window=adx_len)
    st_trend = _supertrend(df, period=st_period, factor=st_factor)
    ichi = _ichimoku(df, conv=ich_conv, base=ich_base, span_b=ich_span_b)
    k, d = _stoch_rsi(close, window=14, smooth_k=3, smooth_d=3)
    ms = _market_structure(df, lookback=ms_lookback, pivot_span=ms_pivot_span)

    # אותות כיווניים
    votes = 0
    reasons: List[str] = []

    if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
        votes += 1; reasons.append("EMA fast>slow")
    elif ema_fast.iloc[-1] < ema_slow.iloc[-1]:
        votes -= 1; reasons.append("EMA fast<slow")

    if st_trend.iloc[-1] == 1:
        votes += 1; reasons.append("Supertrend UP")
    elif st_trend.iloc[-1] == -1:
        votes -= 1; reasons.append("Supertrend DOWN")

    # Ichimoku: מחוץ/בתוך ענן
    span_a = ichi["span_a"].iloc[-1]
    span_b = ichi["span_b"].iloc[-1]
    cloud_top = max(span_a, span_b) if not (pd.isna(span_a) or pd.isna(span_b)) else None
    cloud_bot = min(span_a, span_b) if not (pd.isna(span_a) or pd.isna(span_b)) else None
    if cloud_top is not None and cloud_bot is not None:
        if close.iloc[-1] > cloud_top:
            votes += 1; reasons.append("Above Cloud")
        elif close.iloc[-1] < cloud_bot:
            votes -= 1; reasons.append("Below Cloud")

    if ms["structure"] == "HH-HL":
        votes += 1; reasons.append("Market Structure: HH-HL")
    elif ms["structure"] == "LH-LL":
        votes -= 1; reasons.append("Market Structure: LH-LL")

    # ADX כחוזק מגמה
    adx_last = float(adx.iloc[-1]) if not math.isnan(adx.iloc[-1]) else 0.0
    has_trend_strength = adx_last >= float(min_adx)
    if has_trend_strength:
        reasons.append(f"ADX {adx_last:.1f}≥{min_adx}")

    # StochRSI לסינון קצה
    k_last = float(k.iloc[-1]) if not math.isnan(k.iloc[-1]) else 0.5
    d_last = float(d.iloc[-1]) if not math.isnan(d.iloc[-1]) else 0.5
    stoch_note = None
    if k_last < 0.2 and k_last > d_last:
        votes += 0.5; stoch_note = "StochRSI Bullish"
    elif k_last > 0.8 and k_last < d_last:
        votes -= 0.5; stoch_note = "StochRSI Bearish"
    if stoch_note:
        reasons.append(stoch_note)

    # קביעת צד
    side: Optional[str] = "LONG" if votes > 0.5 else ("SHORT" if votes < -0.5 else None)

    # ניקוד 0..10
    #  בסיס: |votes| מקס' ~3.5 -> נרמול ל-10, בונוס קטן ל-ADX חזק
    score = min(10.0, max(0.0, (abs(votes) / 3.5) * 9.0 + (1.0 if has_trend_strength else 0.0)))

    details = {
        "ema_fast": float(ema_fast.iloc[-1]),
        "ema_slow": float(ema_slow.iloc[-1]),
        "adx": adx_last,
        "supertrend": int(st_trend.iloc[-1]),
        "ichimoku": {
            "tenkan": float(ichi["tenkan"].iloc[-1]) if not math.isnan(ichi["tenkan"].iloc[-1]) else None,
            "kijun": float(ichi["kijun"].iloc[-1]) if not math.isnan(ichi["kijun"].iloc[-1]) else None,
            "span_a": float(span_a) if span_a is not None else None,
            "span_b": float(span_b) if span_b is not None else None,
        },
        "stoch_rsi": {"k": k_last, "d": d_last},
        "market_structure": ms,
        "reasons": reasons,
    }
    return details, side, float(round(score, 2))


# ===========================
# API: /scan GET — heartbeat
# ===========================
@router.get("/", operation_id="getScanInfo")
async def get_scan_info() -> Dict[str, Any]:
    return {"ok": _LAST_SCAN_OK, "count": len(_LAST_SIGNALS), "signals": _LAST_SIGNALS}


# ===========================
# API: /scan POST — סימבול יחיד
# ===========================
@router.post("/", operation_id="postScanSingle")
async def post_scan_single(
    payload: Dict[str, Any] = Body(..., embed=False),
) -> Dict[str, Any]:
    symbol = str(payload.get("symbol", "")).upper().strip()
    timeframe = str(payload.get("timeframe", DEFAULT_INTERVAL))
    limit = int(payload.get("limit", DEFAULT_LIMIT))

    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    async with aiohttp.ClientSession(headers={"Accept": "application/json"}) as session:
        df = await _fetch_klines(session, symbol=symbol, interval=timeframe, limit=limit)

    details, side, score = _score_signal(
        df,
        ema_fast_len=21,
        ema_slow_len=50,
        adx_len=14,
        st_period=10,
        st_factor=3.0,
        ich_conv=9,
        ich_base=26,
        ich_span_b=52,
        ms_lookback=5,
        ms_pivot_span=3,
        min_adx=20.0,
    )

    signal = {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "score": score,
        "note": "; ".join(details.get("reasons", []))[:240],
        "details": details,
    }

    global _LAST_SIGNALS, _LAST_SCAN_OK
    _LAST_SIGNALS = [signal]
    _LAST_SCAN_OK = True
    return {"ok": True, "count": 1, "signals": [signal]}


# ===========================
# API: /scan/multi — רשימת סימבולים
# ===========================
async def _scan_one_symbol(
    session: aiohttp.ClientSession,
    symbol: str,
    timeframe: str,
    limit: int,
    params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        df = await _fetch_klines(session, symbol=symbol, interval=timeframe, limit=limit)
        details, side, score = _score_signal(
            df,
            ema_fast_len=int(params["ema_fast"]),
            ema_slow_len=int(params["ema_slow"]),
            adx_len=int(params["adx_len"]),
            st_period=int(params["st_period"]),
            st_factor=float(params["st_factor"]),
            ich_conv=int(params["ich_conv"]),
            ich_base=int(params["ich_base"]),
            ich_span_b=int(params["ich_span_b"]),
            ms_lookback=int(params["ms_lookback"]),
            ms_pivot_span=int(params["ms_pivot_span"]),
            min_adx=float(params["min_adx"]),
        )
        # Trending only filter
        if params.get("trending_only", False):
            adx_ok = float(details["adx"]) >= float(params["min_adx"])
            st_ok = int(details["supertrend"]) != 0
            ema_ok = float(details["ema_fast"]) > float(details["ema_slow"])
            ichi = details["ichimoku"]
            cloud_top = None if ichi["span_a"] is None or ichi["span_b"] is None else max(ichi["span_a"], ichi["span_b"])
            cloud_bot = None if ichi["span_a"] is None or ichi["span_b"] is None else min(ichi["span_a"], ichi["span_b"])
            price = float(df["close"].iloc[-1])
            cloud_ok = (cloud_top is not None and price > cloud_top) or (cloud_bot is not None and price < cloud_bot)
            if not (adx_ok and (st_ok or ema_ok or cloud_ok)):
                return None

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "score": score,
            "note": "; ".join(details.get("reasons", []))[:240],
            "details": details,
        }
    except Exception as e:
        logger.warning("scan %s failed: %s", symbol, e)
        return None

@router.post("/multi", operation_id="postScanMulti")
async def post_scan_multi(
    payload: Dict[str, Any] = Body(..., embed=False),
) -> Dict[str, Any]:
    symbols: List[str] = list(map(lambda s: s.upper().strip(), payload.get("symbols", [])))
    timeframe = str(payload.get("timeframe", DEFAULT_INTERVAL))
    limit = int(payload.get("limit", DEFAULT_LIMIT))
    if not symbols:
        raise HTTPException(status_code=400, detail="symbols[] is required")

    # פרמטרי ניקוד ברירות מחדל
    params = {
        "trending_only": bool(payload.get("trending_only", False)),
        "min_adx": float(payload.get("min_adx", 20.0)),
        "ema_fast": int(payload.get("ema_fast", 21)),
        "ema_slow": int(payload.get("ema_slow", 50)),
        "adx_len": int(payload.get("adx_len", 14)),
        "st_period": int(payload.get("st_period", 10)),
        "st_factor": float(payload.get("st_factor", 3.0)),
        "ich_conv": int(payload.get("ich_conv", 9)),
        "ich_base": int(payload.get("ich_base", 26)),
        "ich_span_b": int(payload.get("ich_span_b", 52)),
        "ms_lookback": int(payload.get("ms_lookback", 5)),
        "ms_pivot_span": int(payload.get("ms_pivot_span", 3)),
    }

    concurrency = int(payload.get("concurrency", 16))
    sem = asyncio.Semaphore(concurrency)

    async def _wrapped(symbol: str, session: aiohttp.ClientSession):
        async with sem:
            return await _scan_one_symbol(session, symbol, timeframe, limit, params)

    async with aiohttp.ClientSession(headers={"Accept": "application/json"}) as session:
        results = await asyncio.gather(*[_wrapped(s, session) for s in symbols], return_exceptions=False)

    signals = [r for r in results if r]
    signals.sort(key=lambda x: (x["score"] or 0.0), reverse=True)

    global _LAST_SIGNALS, _LAST_SCAN_OK
    _LAST_SIGNALS = signals
    _LAST_SCAN_OK = True
    return {"ok": True, "count": len(signals), "signals": signals}


# ===========================
# API: /scan/top-volume — הרחבה
# ===========================
@router.get("/top-volume", operation_id="getScanTopVolume")
async def get_scan_top_volume(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),

    trending_only: bool = Query(False, description="אם true – מחזיר רק סימבולים בטרנד פעיל"),
    min_adx: float = Query(20.0, ge=5.0, le=60.0),

    ema_fast: int = Query(21, ge=3, le=200),
    ema_slow: int = Query(50, ge=5, le=400),
    adx_len: int = Query(14, ge=5, le=50),

    st_period: int = Query(10, ge=5, le=50),
    st_factor: float = Query(3.0, ge=1.0, le=10.0),

    ich_conv: int = Query(9, ge=5, le=50),
    ich_base: int = Query(26, ge=10, le=100),
    ich_span_b: int = Query(52, ge=20, le=200),

    ms_lookback: int = Query(5, ge=2, le=20),
    ms_pivot_span: int = Query(3, ge=1, le=10),

    concurrency: int = Query(16, ge=2, le=64),
) -> Dict[str, Any]:
    # 1) קבלת רשימת סימבולים
    if _top_symbols_func:
        try:
            top = await _maybe_async(_top_symbols_func, market=market, quote=quote, limit=limit)
            symbols: List[str] = top.get("symbols", []) if isinstance(top, dict) else list(top)
        except Exception as e:
            logger.warning("top-volume fetch failed (%s) — fallback to BTC/ETH", e)
            symbols = ["BTCUSDT", "ETHUSDT"]
    else:
        symbols = ["BTCUSDT", "ETHUSDT"]

    params = {
        "trending_only": trending_only,
        "min_adx": float(min_adx),
        "ema_fast": int(ema_fast),
        "ema_slow": int(ema_slow),
        "adx_len": int(adx_len),
        "st_period": int(st_period),
        "st_factor": float(st_factor),
        "ich_conv": int(ich_conv),
        "ich_base": int(ich_base),
        "ich_span_b": int(ich_span_b),
        "ms_lookback": int(ms_lookback),
        "ms_pivot_span": int(ms_pivot_span),
    }

    sem = asyncio.Semaphore(concurrency)

    async def _wrapped(symbol: str, session: aiohttp.ClientSession):
        async with sem:
            return await _scan_one_symbol(session, symbol, timeframe, bars, params)

    async with aiohttp.ClientSession(headers={"Accept": "application/json"}) as session:
        results = await asyncio.gather(*[_wrapped(s, session) for s in symbols], return_exceptions=False)

    signals = [r for r in results if r]
    signals.sort(key=lambda x: (x["score"] or 0.0), reverse=True)

    global _LAST_SIGNALS, _LAST_SCAN_OK
    _LAST_SIGNALS = signals
    _LAST_SCAN_OK = True
    return {"ok": True, "count": len(signals), "signals": signals}


# ===========================
# עזר: קריאה לפונקציה ייתכן סינכרונית
# ===========================
async def _maybe_async(func, *args, **kwargs):
    res = func(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res




