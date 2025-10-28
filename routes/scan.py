# routes/scan.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import asyncio
from typing import List, Optional, Dict, Any, Union

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

# ----- Optional checklist scoring (safe fallback) -----
try:
    from utils.pretrade_checklist import compute_pretrade_score  # type: ignore
except Exception:
    compute_pretrade_score = None  # type: ignore

# ----- Optional metrics (safe fallback) -----
try:
    from utils.metrics_tracker import (
        inc_scan_eval,
        inc_scan_passed,
        inc_scan_blocked,
        set_last_entry_score,
    )  # type: ignore
except Exception:
    def inc_scan_eval():  # type: ignore
        pass
    def inc_scan_passed():  # type: ignore
        pass
    def inc_scan_blocked():  # type: ignore
        pass
    def set_last_entry_score(_):  # type: ignore
        pass

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")
ENTRY_SCORE_MIN = float(os.getenv("ENTRY_SCORE_MIN", "0") or 0)
ENTRY_SCORE_INTERVAL = (os.getenv("ENTRY_SCORE_INTERVAL", "15m") or "15m").strip()
BIN_TIMEOUT_SEC = float(os.getenv("BIN_TIMEOUT_SEC", "10") or 10)

router = APIRouter(prefix="/scan", tags=["Scan"])


# ===================== Models =====================
if _PYD_V2:
    class IndicatorSet(BaseModel):
        model_config = ConfigDict(extra="ignore")
        rsi: Optional[float] = None
        ema_21: Optional[float] = None
        adx: Optional[float] = None
        atr: Optional[float] = None
        vwap_trend: Optional[bool] = None
        ema_50: Optional[float] = None
        macd: Optional[float] = None
        macd_signal: Optional[float] = None
        macd_hist: Optional[float] = None
        bb_mid: Optional[float] = None
        bb_upper: Optional[float] = None
        bb_lower: Optional[float] = None
else:
    class IndicatorSet(BaseModel):
        class Config:
            extra = "ignore"
        rsi: Optional[float] = None
        ema_21: Optional[float] = None
        adx: Optional[float] = None
        atr: Optional[float] = None
        vwap_trend: Optional[bool] = None
        ema_50: Optional[float] = None
        macd: Optional[float] = None
        macd_signal: Optional[float] = None
        macd_hist: Optional[float] = None
        bb_mid: Optional[float] = None
        bb_upper: Optional[float] = None
        bb_lower: Optional[float] = None


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


# ===================== Binance helpers =====================
async def _fetch_json(url: str, params: Dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=httpx.Timeout(BIN_TIMEOUT_SEC)) as cli:
        r = await cli.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def _fetch_klines_async(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    sym = symbol.strip().upper()
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
    # Ensure numeric
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["open", "high", "low", "close", "volume"]]


# ===== helper: ADX/ATR% מתוך df =====
def _adx_atr_pct_from_df(df: pd.DataFrame, period: int = 14) -> Dict[str, float]:
    try:
        if df is None or len(df) < period + 2:
            return {"adx": 0.0, "atr_pct": 0.0}
        highs = df["high"].to_list()
        lows = df["low"].to_list()
        closes = df["close"].to_list()
        trs: List[float] = []
        plus_dm: List[float] = []
        minus_dm: List[float] = []
        for i in range(1, len(closes)):
            h, l, ph, pl, pc = highs[i], lows[i], highs[i - 1], lows[i - 1], closes[i - 1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            up_move = h - ph
            down_move = pl - l
            plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
            minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)

        def _wilder(vs: List[float]) -> List[float]:
            if len(vs) < period:
                return []
            out = [sum(vs[:period]) / period]
            for v in vs[period:]:
                out.append((out[-1] * (period - 1) + v) / period)
            return out

        atr_s = _wilder(trs)
        p_s = _wilder(plus_dm)
        m_s = _wilder(minus_dm)
        if not (atr_s and p_s and m_s):
            return {"adx": 0.0, "atr_pct": 0.0}

        plus_di = [(p / atr_s[i]) * 100 if atr_s[i] > 0 else 0.0 for i, p in enumerate(p_s)]
        minus_di = [(m / atr_s[i]) * 100 if atr_s[i] > 0 else 0.0 for i, m in enumerate(m_s)]
        dx: List[float] = []
        for i in range(min(len(plus_di), len(minus_di))):
            s = plus_di[i] + minus_di[i]
            d = abs(plus_di[i] - minus_di[i])
            dx.append((d / s) * 100 if s > 0 else 0.0)
        adx_s = _wilder(dx)
        adx = adx_s[-1] if adx_s else 0.0
        price = float(closes[-1])
        atr = float(atr_s[-1]) if atr_s else 0.0
        atr_pct = (atr / price) * 100.0 if price > 0 else 0.0
        return {"adx": float(adx), "atr_pct": float(atr_pct)}
    except Exception:
        return {"adx": 0.0, "atr_pct": 0.0}


# ===================== Core helpers =====================
async def _score_from_df(df: pd.DataFrame) -> Dict[str, Any]:
    """
    מחזיר dict עם score ו-features; אם compute_pretrade_score לא זמין/אין df -> score=None.
    """
    if compute_pretrade_score is None or df is None or df.empty:
        return {"score": None, "features": None}
    try:
        # Build klines-like structure
        k_df = df.reset_index(drop=True).assign(
            open_time=0, close_time=0, qv=0, nTrades=0, taker_base=0, taker_quote=0, x=0
        )
        kl = [
            [
                int(getattr(r, "open_time", 0)),
                float(r.open), float(r.high), float(r.low), float(r.close),
                float(getattr(r, "volume", 0.0)),
                0, 0, 0, 0, 0, 0,
            ]
            for _, r in k_df.iterrows()
        ]
        # Local ADX/ATR%
        adx_atr = _adx_atr_pct_from_df(df, period=14)
        inc_scan_eval()
        res = compute_pretrade_score(kl, adx=float(adx_atr["adx"]), atr_pct=float(adx_atr["atr_pct"])) or {}
        score = float(res.get("score", 0.0))
        features = dict(res.get("features") or {})
        # Metrics + threshold
        set_last_entry_score(score)
        if ENTRY_SCORE_MIN > 0:
            if score >= ENTRY_SCORE_MIN:
                inc_scan_passed()
            else:
                inc_scan_blocked()
        return {"score": score, "features": features}
    except Exception:
        # Do not break API on scoring issue
        return {"score": None, "features": None}


# ===================== Programmatic API (alias-friendly) =====================
async def scan_symbols(
    symbols: Union[str, List[str]],
    interval: str = ENTRY_SCORE_INTERVAL,
    limit: int = 200,
) -> ScanResponse:
    """
    פונקציה לשימוש פנימי/אליאס: מקבלת CSV או List[str] ומחזירה ScanResponse.
    """
    if isinstance(symbols, str):
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        syms = [s.strip().upper() for s in symbols if s and isinstance(s, str)]
    if not syms:
        wl = (os.getenv("WATCHLIST") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,NEARUSDT").split(",")
        syms = [s.strip().upper() for s in wl if s.strip()]

    async def _one(sym: str) -> ScanSignal:
        try:
            df = await _fetch_klines_async(sym, interval, limit)
            if df.empty:
                return ScanSignal(symbol=sym, interval=interval, ok=False, error="no data")
            scored = await _score_from_df(df)
            return ScanSignal(symbol=sym, interval=interval, score=scored["score"], features=scored["features"], ok=True)
        except Exception as e:
            return ScanSignal(symbol=sym, interval=interval, ok=False, error=str(e))

    results = await asyncio.gather(*[_one(s) for s in syms], return_exceptions=False)
    ok_any = any(r.ok for r in results)
    return ScanResponse(ok=ok_any, count_total=len(syms), returned=len(results), signals=list(results))


# ===================== Endpoints =====================
@router.get("/info", response_model=ScanResponse, summary="Basic Scan Info")
async def scan_info(
    symbol: str = Query(..., description="Symbol e.g. BTCUSDT"),
    interval: str = Query(default=ENTRY_SCORE_INTERVAL, description="Kline interval"),
    limit: int = Query(200, ge=50, le=200),
) -> ScanResponse:
    try:
        df = await _fetch_klines_async(symbol, interval, limit)
        if df.empty:
            return ScanResponse(ok=False, count_total=1, returned=0, error="no data")

        # Optional indicators (if utils.indicators exists)
        try:
            from utils.indicators import prepare_indicators_for_backtest  # type: ignore
            ind_df = await asyncio.to_thread(prepare_indicators_for_backtest, df)
            row = {k: (float(v) if pd.notna(v) else None) for k, v in ind_df.iloc[-1].to_dict().items()}
            indicators = IndicatorSet(**row)
        except Exception:
            indicators = None

        scored = await _score_from_df(df)
        sig = ScanSignal(
            symbol=symbol.upper(),
            interval=interval,
            indicators=indicators,
            score=scored["score"],
            features=scored["features"],
            ok=True,
        )
        return ScanResponse(ok=True, count_total=1, returned=1, signals=[sig])
    except Exception as e:
        return ScanResponse(ok=False, count_total=1, returned=0, error=str(e))


@router.get("", response_model=ScanResponse, summary="Multi-symbol scan")
async def scan_multi(
    symbols: Optional[str] = Query(None, description="CSV of symbols, e.g. BTCUSDT,ETHUSDT"),
    interval: str = Query(default=ENTRY_SCORE_INTERVAL, description="Kline interval"),
    limit: int = Query(200, ge=50, le=200),
) -> ScanResponse:
    if symbols:
        return await scan_symbols(symbols=symbols, interval=interval, limit=limit)
    wl = (os.getenv("WATCHLIST") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,NEARUSDT").split(",")
    return await scan_symbols(symbols=[s.strip().upper() for s in wl if s.strip()], interval=interval, limit=limit)


@router.get("/futures/all", summary="Scan all USDT-M perpetuals by 24h quote volume")
async def scan_all_futures(
    limit: int = Query(120, ge=10, le=300),
    min_vol_usdt: float = Query(80_000_000.0, ge=0.0),
) -> Dict[str, Any]:
    """
    מחזיר רשימת סמלים מסוננת מכל ה-USDT-M PERPETUAL, עם נפח 24h >= min_vol_usdt.
    יעיל (bulk): exchangeInfo + ticker/24hr.
    """
    exch = await _fetch_json(f"{FUTURES_BASE}/fapi/v1/exchangeInfo")
    symbols: List[Dict[str, Any]] = exch.get("symbols", [])

    def _allow_symbol(info: Dict[str, Any]) -> bool:
        return (
            info.get("contractType") == "PERPETUAL"
            and info.get("quoteAsset") == "USDT"
            and info.get("status") == "TRADING"
            and info.get("marginAsset") == "USDT"
        )

    cands = [s["symbol"] for s in symbols if _allow_symbol(s)]

    tickers: List[Dict[str, Any]] = await _fetch_json(f"{FUTURES_BASE}/fapi/v1/ticker/24hr")
    volmap = {t["symbol"]: float(t.get("quoteVolume", 0.0) or 0.0) for t in tickers}

    filtered = [s for s in cands if volmap.get(s, 0.0) >= min_vol_usdt]
    filtered.sort(key=lambda s: volmap.get(s, 0.0), reverse=True)
    top = filtered[: max(10, min(limit, 300))]

    return {
        "ok": True,
        "count": len(top),
        "symbols": top,
        "note": "USDT-M PERPETUAL filtered by 24h quoteVolume",
    }


# --- legacy alias (if someone still imports) ---
def run_scan(*_args, **_kwargs):
    return {"ok": True, "data": []}




