# routes/scan.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import math
import asyncio
from typing import List, Optional, Dict, Any, Union, Tuple

import httpx
import pandas as pd  # type: ignore
from fastapi import APIRouter, Query

# ----- Pydantic v1/v2 compatibility -----
try:
    from pydantic import BaseModel, Field, ConfigDict
    _PYD_V2 = True
except Exception:
    from pydantic import BaseModel, Field  # type: ignore
    _PYD_V2 = False

FUTURES_BASE = (os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com") or "").rstrip("/")
BIN_TIMEOUT_SEC = float(os.getenv("BIN_TIMEOUT_SEC", "10") or 10)
ENTRY_SCORE_INTERVAL = (os.getenv("ENTRY_SCORE_INTERVAL", "15m") or "15m").strip()
ENTRY_SCORE_MIN = float(os.getenv("ENTRY_SCORE_MIN", "0") or 0.0)
MIN_24H_QV = float(os.getenv("MIN_VOLUME_24H_USDT", "80000000") or 80_000_000.0)  # ברירת מחדל 80M USDT

router = APIRouter(prefix="/scan", tags=["Scan"])

# ===================== Models =====================
if _PYD_V2:
    class IndicatorSet(BaseModel):
        model_config = ConfigDict(extra="ignore")
        rsi: Optional[float] = None
        ema_21: Optional[float] = None
        ema_50: Optional[float] = None
        adx: Optional[float] = None
        atr: Optional[float] = None
        atr_pct: Optional[float] = None
        macd: Optional[float] = None
        macd_signal: Optional[float] = None
        macd_hist: Optional[float] = None
        bb_mid: Optional[float] = None
        bb_upper: Optional[float] = None
        bb_lower: Optional[float] = None
        bb_width_pct: Optional[float] = None
else:
    class IndicatorSet(BaseModel):
        class Config:
            extra = "ignore"
        rsi: Optional[float] = None
        ema_21: Optional[float] = None
        ema_50: Optional[float] = None
        adx: Optional[float] = None
        atr: Optional[float] = None
        atr_pct: Optional[float] = None
        macd: Optional[float] = None
        macd_signal: Optional[float] = None
        macd_hist: Optional[float] = None
        bb_mid: Optional[float] = None
        bb_upper: Optional[float] = None
        bb_lower: Optional[float] = None
        bb_width_pct: Optional[float] = None


class ScanSignal(BaseModel):
    symbol: str
    interval: str
    indicators: Optional[IndicatorSet] = None
    score: Optional[float] = None
    features: Optional[Dict[str, Any]] = None
    ok: bool = True
    error: Optional[str] = None


class ScanResponse(BaseModel):
    ok: bool = True
    count_total: int
    returned: int
    signals: List[ScanSignal] = Field(default_factory=list)
    error: Optional[str] = None

# ===================== HTTP helpers =====================
async def _get_json(url: str, params: Dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=httpx.Timeout(BIN_TIMEOUT_SEC)) as cli:
        r = await cli.get(url, params=params)
        r.raise_for_status()
        return r.json()

# ===================== Binance data =====================
async def _fetch_klines(symbol: str, interval: str = "15m", limit: int = 300) -> pd.DataFrame:
    sym = str(symbol).strip().upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    async with httpx.AsyncClient(timeout=httpx.Timeout(BIN_TIMEOUT_SEC)) as cli:
        r = await cli.get(url, params={"symbol": sym, "interval": interval, "limit": int(limit)})
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

async def _futures_usdt_perps(min_qv: float) -> Tuple[List[str], Dict[str,float]]:
    exch = await _get_json(f"{FUTURES_BASE}/fapi/v1/exchangeInfo")
    symbols = [s["symbol"] for s in exch.get("symbols", []) if
               s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT"
               and s.get("status") == "TRADING" and s.get("marginAsset") == "USDT"]
    tickers = await _get_json(f"{FUTURES_BASE}/fapi/v1/ticker/24hr")
    qv = {t["symbol"]: float(t.get("quoteVolume", 0) or 0.0) for t in tickers}
    filtered = [s for s in symbols if qv.get(s, 0.0) >= min_qv]
    filtered.sort(key=lambda s: qv.get(s, 0.0), reverse=True)
    return filtered, qv

# ===================== Indicators (no external deps) =====================
def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series,pd.Series,pd.Series]:
    ema_fast = _ema(close, 12)
    ema_slow = _ema(close, 26)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    tr = _atr(high, low, close, period=1)
    atr_n = tr.ewm(alpha=1/period, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr_n.replace(0, 1e-12))
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr_n.replace(0, 1e-12))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def _bb(close: pd.Series, period: int = 20, mult: float = 2.0) -> Tuple[pd.Series,pd.Series,pd.Series,pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    width_pct = ((upper - lower) / mid.replace(0, 1e-12)) * 100.0
    return mid, upper, lower, width_pct

def compute_indicators(df: pd.DataFrame) -> IndicatorSet:
    if df is None or df.empty or len(df) < 50:
        return IndicatorSet()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)
    rsi = _rsi(close, 14)
    atr = _atr(high, low, close, 14)
    adx = _adx(high, low, close, 14)
    macd_line, macd_sig, macd_hist = _macd(close, 12, 26, 9)
    bb_mid, bb_up, bb_lo, bb_w = _bb(close, 20, 2.0)

    price = float(close.iloc[-1])
    atr_pct = float(atr.iloc[-1]) / (price if price > 0 else 1e-12) * 100.0

    return IndicatorSet(
        rsi=float(rsi.iloc[-1]),
        ema_21=float(ema21.iloc[-1]),
        ema_50=float(ema50.iloc[-1]),
        adx=float(adx.iloc[-1]),
        atr=float(atr.iloc[-1]),
        atr_pct=float(atr_pct),
        macd=float(macd_line.iloc[-1]),
        macd_signal=float(macd_sig.iloc[-1]),
        macd_hist=float(macd_hist.iloc[-1]),
        bb_mid=float(bb_mid.iloc[-1]) if not math.isnan(bb_mid.iloc[-1]) else None,
        bb_upper=float(bb_up.iloc[-1]) if not math.isnan(bb_up.iloc[-1]) else None,
        bb_lower=float(bb_lo.iloc[-1]) if not math.isnan(bb_lo.iloc[-1]) else None,
        bb_width_pct=float(bb_w.iloc[-1]) if not math.isnan(bb_w.iloc[-1]) else None,
    )

# ===================== Scoring (0–10) =====================
def compute_quality_score(ind: IndicatorSet, price: Optional[float]) -> Tuple[float, Dict[str, Any]]:
    """
    חישוב נקודות לפי כללים קבועים:
    - EMA trend: 2 נק' אם ema21>ema50 (לונג bias), 2 נק' אם ema21<ema50 (שורט bias) -> נסמן 'trend'
    - ADX: 1 נק' אם ADX>=18, 2 נק' אם ADX>=22, 3 נק' אם ADX>=28
    - ATR%: 1 נק' אם 0.5–2.5%; 0 נק' אם נמוך מדי/גבוה מדי
    - MACD: 1 נק' אם hist>0 (לונג bias) או <0 (שורט bias)
    - RSI: 1 נק' אם בין 40–60, 0.5 נק' אם 35–65
    - BB width: 1 נק' אם 4–15% (לא דחוס מדי ולא מפוצץ)
    סה"כ capped ל־10.
    """
    pts = 0.0
    feats: Dict[str, Any] = {}

    ema21 = ind.ema_21 or None
    ema50 = ind.ema_50 or None
    adx = ind.adx or 0.0
    atr_pct = ind.atr_pct or 0.0
    hist = ind.macd_hist or 0.0
    rsi = ind.rsi or 0.0
    bbw = ind.bb_width_pct or 0.0

    # Trend by EMAs
    trend = None
    if ema21 is not None and ema50 is not None:
        if ema21 > ema50:
            pts += 2.0
            trend = "LONG"
        elif ema21 < ema50:
            pts += 2.0
            trend = "SHORT"
        feats["ema_trend"] = trend

    # ADX strength
    if adx >= 28:
        pts += 3.0
    elif adx >= 22:
        pts += 2.0
    elif adx >= 18:
        pts += 1.0
    feats["adx"] = adx

    # ATR%
    if 0.5 <= atr_pct <= 2.5:
        pts += 1.0
    feats["atr_pct"] = atr_pct

    # MACD hist sign
    if hist > 0 and trend == "LONG":
        pts += 1.0
    elif hist < 0 and trend == "SHORT":
        pts += 1.0
    feats["macd_hist"] = hist

    # RSI range
    if 40 <= rsi <= 60:
        pts += 1.0
    elif 35 <= rsi <= 65:
        pts += 0.5
    feats["rsi"] = rsi

    # Bollinger width sanity
    if 4.0 <= bbw <= 15.0:
        pts += 1.0
    feats["bb_width_pct"] = bbw

    score = min(10.0, round(pts, 2))
    feats["score_breakdown"] = pts
    feats["trend_bias"] = trend
    feats["price"] = price
    return score, feats

# ===================== Core API helpers =====================
async def _analyze_symbol(sym: str, interval: str, limit: int) -> ScanSignal:
    try:
        df = await _fetch_klines(sym, interval, limit)
        if df.empty:
            return ScanSignal(symbol=sym.upper(), interval=interval, ok=False, error="no data")
        ind = compute_indicators(df)
        price = float(df["close"].iloc[-1])
        score, feats = compute_quality_score(ind, price)
        if ENTRY_SCORE_MIN > 0 and (score is None or score < ENTRY_SCORE_MIN):
            feats["blocked_below_threshold"] = ENTRY_SCORE_MIN
        return ScanSignal(
            symbol=sym.upper(),
            interval=interval,
            indicators=ind,
            score=score,
            features=feats,
            ok=True,
        )
    except Exception as e:
        return ScanSignal(symbol=sym.upper(), interval=interval, ok=False, error=str(e))

async def _gather_limit(coros: List[Any], limit: int = 20) -> List[Any]:
    sem = asyncio.Semaphore(limit)
    async def _wrap(c):
        async with sem:
            return await c
    return await asyncio.gather(*[_wrap(c) for c in coros], return_exceptions=False)

# ===================== Endpoints =====================
@router.get("/info", response_model=ScanResponse, summary="Analyze single symbol")
async def scan_info(
    symbol: str = Query(..., description="Symbol e.g. BTCUSDT"),
    interval: str = Query(default=ENTRY_SCORE_INTERVAL, description="Kline interval"),
    limit: int = Query(200, ge=50, le=300),
) -> ScanResponse:
    sig = await _analyze_symbol(symbol, interval, limit)
    return ScanResponse(ok=sig.ok, count_total=1, returned=1 if sig.ok else 0,
                        signals=[sig] if sig.ok else [], error=None if sig.ok else sig.error)

@router.get("", response_model=ScanResponse, summary="Analyze multiple symbols (CSV)")
async def scan_multi(
    symbols: Optional[str] = Query(None, description="CSV e.g. BTCUSDT,ETHUSDT"),
    interval: str = Query(default=ENTRY_SCORE_INTERVAL, description="Kline interval"),
    limit: int = Query(200, ge=50, le=300),
    concurrency: int = Query(16, ge=1, le=64),
) -> ScanResponse:
    if symbols:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        wl = (os.getenv("WATCHLIST") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,NEARUSDT").split(",")
        syms = [s.strip().upper() for s in wl if s.strip()]
    results: List[ScanSignal] = await _gather_limit(
        [ _analyze_symbol(s, interval, limit) for s in syms ],
        limit=concurrency
    )
    ok_any = any(r.ok for r in results)
    return ScanResponse(ok=ok_any, count_total=len(syms), returned=len(results), signals=results)

@router.get("/futures/all", summary="List top USDT-M perps by 24h quote volume")
async def scan_all_futures(
    limit: int = Query(120, ge=10, le=300),
    min_vol_usdt: float = Query(MIN_24H_QV, ge=0.0),
) -> Dict[str, Any]:
    """
    מחזיר רשימת סמלים מכל USDT-M PERPETUAL מסוננים לפי quoteVolume 24h.
    """
    syms, qv = await _futures_usdt_perps(min_vol_usdt)
    top = syms[: max(10, min(limit, 300))]
    return {"ok": True, "count": len(top), "symbols": top, "min_vol_usdt": float(min_vol_usdt)}

@router.get("/futures/scan", response_model=ScanResponse, summary="Scan USDT-M perps (filtered by 24h quoteVolume)")
async def scan_futures_filtered(
    interval: str = Query(default=ENTRY_SCORE_INTERVAL, description="Kline interval"),
    limit: int = Query(200, ge=50, le=300),
    min_vol_usdt: float = Query(MIN_24H_QV, ge=0.0),
    max_symbols: int = Query(120, ge=10, le=300),
    concurrency: int = Query(16, ge=1, le=64),
) -> ScanResponse:
    syms, qv = await _futures_usdt_perps(min_vol_usdt)
    syms = syms[:max_symbols]
    results: List[ScanSignal] = await _gather_limit(
        [ _analyze_symbol(s, interval, limit) for s in syms ],
        limit=concurrency
    )
    ok_any = any(r.ok for r in results)
    return ScanResponse(ok=ok_any, count_total=len(syms), returned=len(results), signals=results)

# --- legacy alias (keep API compatibility) ---
def run_scan(*_args, **_kwargs):
    return {"ok": True, "data": []}


