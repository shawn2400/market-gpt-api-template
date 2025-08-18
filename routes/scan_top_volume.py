# routes/scan_top_volume.py
from __future__ import annotations
import asyncio
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from fastapi import APIRouter, Query, Header, HTTPException, status, Depends

# ==== Auth (Bearer) ====
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    # אם יש API_BEARER_TOKEN נדרוש אותו; אם לא – נרשה (dev/public mode)
    def require_bearer_token(authorization: str = Header(default="")):
        expected = os.getenv("API_BEARER_TOKEN", "").strip()
        if not expected:
            return None
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        got = authorization.split(" ", 1)[1].strip()
        if got != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        return None

# ==== Binance bases ====
FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
SPOT_BASE    = os.getenv("BINANCE_SPOT_HTTP_BASE",    "https://api.binance.com")

# ==== HTTP session ====
_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 scan-topvol",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

# שים לב: אם API_BEARER_TOKEN מוגדר – הנתיב יהיה מוגן; אם לא – ציבורי.
router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

# --------- Top Volume (מעדיף utils/top_volume אם קיים) ---------
def _get_top_symbols(market: str, quote: str, limit: int) -> List[str]:
    try:
        from utils.top_volume import get_top_volume_symbols  # type: ignore
        ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
        if ok and symbols:
            return symbols
    except Exception:
        pass

    # fallback ישיר
    url = f"{FUTURES_BASE}/fapi/v1/ticker/24hr" if market == "futures" else f"{SPOT_BASE}/api/v3/ticker/24hr"
    try:
        r = _S.get(url, timeout=8)
        r.raise_for_status()
        items = r.json()
        rows: List[tuple[str, float]] = []
        for it in items:
            sym = str(it.get("symbol") or "").upper()
            if not sym.endswith(quote.upper()):
                continue
            try:
                qv = float(it.get("quoteVolume") or 0.0)
            except Exception:
                qv = 0.0
            rows.append((sym, qv))
        rows.sort(key=lambda t: t[1], reverse=True)
        return [s for s, _ in rows[: max(1, int(limit))]]
    except Exception:
        return []

# --------- Klines ---------
def _klines(symbol: str, interval: str, limit: int, market: str) -> Optional[pd.DataFrame]:
    try:
        base = FUTURES_BASE if market == "futures" else SPOT_BASE
        path = "fapi/v1/klines" if market == "futures" else "api/v3/klines"
        url = f"{base}/{path}"
        r = _S.get(url, params={"symbol": symbol, "interval": interval, "limit": int(limit)}, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        if not data:
            return None
        df = pd.DataFrame(
            data,
            columns=[
                "openTime","open","high","low","close","volume",
                "closeTime","qv","nTrades","takerBase","takerQuote","x"
            ],
        )
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["open","high","low","close"], inplace=True)
        df["timestamp"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        return df[["timestamp","open","high","low","close","volume"]]
    except Exception:
        return None

# --------- אינדיקטורים קלים (ללא תלות חיצונית) ---------
def _ema(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(n))
    return s.ewm(span=n, adjust=False).mean()

def _rma(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(n))
    return s.ewm(alpha=1.0/n, adjust=False).mean()

def _atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return _rma(tr, n)

def _adx(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    up = h.diff()
    dn = -l.diff()
    plus_dm  = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    atr_rma = _atr(h, l, c, n).replace(0, np.nan)
    plus_di = 100.0 * _rma(plus_dm, n) / atr_rma
    minus_di= 100.0 * _rma(minus_dm, n) / atr_rma
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _rma(dx.fillna(0.0), n).fillna(0.0)

def _stoch_kd(h: pd.Series, l: pd.Series, c: pd.Series, win: int = 14, smooth: int = 3):
    ll = l.rolling(win, min_periods=1).min()
    hh = h.rolling(win, min_periods=1).max()
    k = 100.0 * ((c - ll) / (hh - ll).replace(0, np.nan))
    d = k.rolling(smooth, min_periods=1).mean()
    return k.fillna(0.0), d.fillna(0.0)

def _supertrend(h: pd.Series, l: pd.Series, c: pd.Series, period: int = 10, factor: float = 3.0) -> pd.Series:
    atr = _atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    upper = hl2 + factor * atr
    lower = hl2 - factor * atr
    fu = upper.copy()
    fl = lower.copy()
    st = pd.Series(index=c.index, dtype="float64")
    fu.iloc[0] = upper.iloc[0]
    fl.iloc[0] = lower.iloc[0]
    st.iloc[0] = upper.iloc[0]
    for i in range(1, len(c)):
        fu.iloc[i] = upper.iloc[i] if (upper.iloc[i] < fu.iloc[i-1] or c.iloc[i-1] > fu.iloc[i-1]) else fu.iloc[i-1]
        fl.iloc[i] = lower.iloc[i] if (lower.iloc[i] > fl.iloc[i-1] or c.iloc[i-1] < fl.iloc[i-1]) else fl.iloc[i-1]
        if st.iloc[i-1] == fu.iloc[i-1]:
            st.iloc[i] = fu.iloc[i] if c.iloc[i] <= fu.iloc[i] else fl.iloc[i]
        else:
            st.iloc[i] = fl.iloc[i] if c.iloc[i] >= fl.iloc[i] else fu.iloc[i]
    return st

def _ichimoku_state(h: pd.Series, l: pd.Series, c: pd.Series, conv=9, base=26, span_b=52) -> pd.Series:
    conv_line = (h.rolling(conv).max() + l.rolling(conv).min()) / 2.0
    base_line = (h.rolling(base).max() + l.rolling(base).min()) / 2.0
    span_a = (conv_line + base_line) / 2.0
    span_b_s = (h.rolling(span_b).max() + l.rolling(span_b).min()) / 2.0
    top = np.maximum(span_a, span_b_s)
    bot = np.minimum(span_a, span_b_s)
    state = np.where(c > top, "BULLISH", np.where(c < bot, "BEARISH", "NEUTRAL"))
    return pd.Series(state, index=c.index)

def _add_indicators(df: pd.DataFrame,
                    ema_fast=21, ema_slow=50, adx_len=14,
                    st_period=10, st_factor=3.0,
                    ich_conv=9, ich_base=26, ich_span_b=52) -> pd.DataFrame:
    d = df.copy()
    c, h, l = d["close"], d["high"], d["low"]
    d["ema_fast"] = _ema(c, ema_fast)
    d["ema_slow"] = _ema(c, ema_slow)
    d["adx"] = _adx(h, l, c, adx_len)
    k, kd = _stoch_kd(h, l, c, 14, 3)
    d["stoch_k"], d["stoch_d"] = k, kd
    d["atr"] = _atr(h, l, c, max(14, st_period))
    d["supertrend"] = _supertrend(h, l, c, st_period, float(st_factor))
    d["ichimoku_state"] = _ichimoku_state(h, l, c, ich_conv, ich_base, ich_span_b)
    d["trend_dir"] = np.where(d["ema_fast"] > d["ema_slow"], "UP",
                       np.where(d["ema_fast"] < d["ema_slow"], "DOWN", "FLAT"))
    d["trending"] = (d["adx"] >= 20.0) & (d["trend_dir"] != "FLAT")
    return d

def _score_row(row: pd.Series) -> tuple[float, str, int, str]:
    try:
        adx = float(row.get("adx") or 0.0)
        ema_fast = float(row.get("ema_fast") or 0.0)
        ema_slow = float(row.get("ema_slow") or 0.0)
        close = float(row.get("close") or 0.0)
        st_val = float(row.get("supertrend") or close)
        ich = str(row.get("ichimoku_state") or "NEUTRAL").upper()
        k = float(row.get("stoch_k") or 50.0)
        d = float(row.get("stoch_d") or 50.0)
        trending = bool(row.get("trending") is True)
        trend_dir = str(row.get("trend_dir") or "FLAT").upper()

        bull = (1 if ema_fast > ema_slow else 0) + (1 if close > st_val else 0) + (1 if ich == "BULLISH" else 0)
        bear = (1 if ema_fast < ema_slow else 0) + (1 if close < st_val else 0) + (1 if ich == "BEARISH" else 0)
        side = "LONG" if bull >= bear else "SHORT"

        dir_score = (max(bull, bear) / 3.0) * 5.0
        adx_score = max(0.0, min(3.0, (adx / 40.0) * 3.0))
        stoch_bonus = 1.0 if ((side == "LONG" and k >= d) or (side == "SHORT" and k <= d)) else 0.0
        tr_bonus = 1.0 if trending else 0.0
        score = float(max(0.0, min(10.0, round(dir_score + adx_score + stoch_bonus + tr_bonus, 2))))
        conf = int(max(0, min(100, round(30 + adx * 2 + (10 if trending else 0) + (5 if dir_score >= 3.5 else 0)))))
        reason = f"{side} • dir={dir_score:.1f}, adx={adx:.1f}, stoch={'K>D' if k>=d else 'K<D'}, ich={ich}, trending={trending}, trend={trend_dir}"
        return score, side, conf, reason
    except Exception:
        return 0.0, "LONG", 50, "scoring_error"

# --------- Endpoint: /scan/top-volume ---------
@router.get(
    "/top-volume",
    summary="Scan top-volume symbols concurrently (extended)",
    operation_id="getScanTopVolume",  # תואם OpenAPI שלך
)
async def scan_top_volume(
    market: str = Query("futures", enum=["futures","spot"]),
    quote:  str = Query("USDT"),
    limit:  int = Query(50, ge=1, le=200),
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

    ms_lookback: int = Query(5, ge=2, le=20),    # תאימות קדימה (לא בשימוש כאן)
    ms_pivot_span: int = Query(3, ge=1, le=10),  # תאימות קדימה (לא בשימוש כאן)

    concurrency: int = Query(16, ge=2, le=64),
) -> Dict[str, Any]:
    symbols = _get_top_symbols(market, quote, limit)
    if not symbols:
        return {"ok": True, "count": 0, "signals": [], "note": "no symbols"}

    sem = asyncio.Semaphore(concurrency)

    async def _scan(sym: str) -> Optional[Dict[str, Any]]:
        async with sem:
            try:
                df = await asyncio.to_thread(_klines, sym, timeframe, bars, market)
                if df is None or df.empty:
                    return None
                ext = await asyncio.to_thread(
                    _add_indicators, df,
                    ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len,
                    st_period=st_period, st_factor=st_factor,
                    ich_conv=ich_conv, ich_base=ich_base, ich_span_b=ich_span_b
                )
                if ext is None or len(ext) == 0:
                    return None
                row = ext.iloc[-1]
                adx_val = float(row.get("adx") or 0.0)

                # Trending check & optional filter
                is_trending = bool(row.get("trending") is True and adx_val >= float(min_adx or 0.0))
                if trending_only and not is_trending:
                    return None

                score, side, conf, reason = _score_row(row)
                if not is_trending:
                    score = round(max(0.0, score - 0.8), 2)
                    reason = (reason + " non-trend")[:140]

                # שמות שדות “ישנים” + החדשים
                ich_raw = str(row.get("ichimoku_state") or "NEUTRAL").upper()
                ich_state = "BULL" if ich_raw == "BULLISH" else ("BEAR" if ich_raw == "BEARISH" else "NEUTRAL")
                trend_dir = str(row.get("trend_dir") or "FLAT").upper()
                ms_trend = "UP" if trend_dir == "UP" else ("DOWN" if trend_dir == "DOWN" else "RANGE")

                return {
                    "symbol": sym,
                    "timeframe": timeframe,
                    "side": side,
                    "score": score,
                    "note": reason,
                    "details": {
                        "close": float(row.get("close") or 0.0),
                        "ema_fast": float(row.get("ema_fast") or 0.0),
                        "ema_slow": float(row.get("ema_slow") or 0.0),
                        "adx": adx_val,
                        "ich_state": ich_state,    # תאימות אחורה
                        "ms_trend": ms_trend,      # תאימות אחורה
                        "trending": is_trending,
                        "confidence": conf,
                        # גם החדשים:
                        "trend_dir": trend_dir,
                        "ichimoku_state": ich_raw,
                        "atr": float(row.get("atr") or 0.0),
                        "stoch_k": float(row.get("stoch_k") or 0.0),
                        "stoch_d": float(row.get("stoch_d") or 0.0),
                        "supertrend": float(row.get("supertrend") or 0.0),
                    },
                }
            except Exception:
                return None

    tasks = [asyncio.create_task(_scan(s)) for s in symbols]
    res = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for r in res:
        if isinstance(r, dict):
            out.append(r)
    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return {"ok": True, "count": len(out), "signals": out}



