# routes/scan.py
from __future__ import annotations
from fastapi import APIRouter, Query
from typing import List, Optional, Dict, Any
import os
import pandas as pd
import httpx
import asyncio

try:
    from pydantic import BaseModel, Field, ConfigDict
    _PYD_V2 = True
except Exception:
    from pydantic import BaseModel, Field
    _PYD_V2 = False

# Checklist scoring (בטוח: אם חסר—לא נופלים)
try:
    from utils.pretrade_checklist import compute_pretrade_score  # type: ignore
except Exception:
    compute_pretrade_score = None  # type: ignore

# Metrics (מונים + עדכון gauge לציון אחרון)
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

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
ENTRY_SCORE_MIN = float(os.getenv("ENTRY_SCORE_MIN", "0") or 0)
ENTRY_SCORE_INTERVAL = os.getenv("ENTRY_SCORE_INTERVAL", "15m")

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
async def _fetch_klines_async(symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
    sym = symbol.strip().upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    url = f"{FUTURES_BASE}/fapi/v1/klines"
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as cli:
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

# ===== helper: ADX/ATR% מתוך df =====
def _adx_atr_pct_from_df(df: pd.DataFrame, period: int = 14) -> Dict[str, float]:
    try:
        if len(df) < period + 2:
            return {"adx": 0.0, "atr_pct": 0.0}
        highs = df["high"].to_list(); lows = df["low"].to_list(); closes = df["close"].to_list()
        trs, plus_dm, minus_dm = [], [], []
        for i in range(1, len(closes)):
            h, l, ph, pl, pc = highs[i], lows[i], highs[i-1], lows[i-1], closes[i-1]
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
            up_move = h-ph; down_move = pl-l
            plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
            minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        def _wilder(vs):
            if len(vs) < period: return []
            out = [sum(vs[:period]) / period]
            for v in vs[period:]:
                out.append((out[-1]*(period-1)+v)/period)
            return out
        atr_s = _wilder(trs); p_s = _wilder(plus_dm); m_s = _wilder(minus_dm)
        if not (atr_s and p_s and m_s): return {"adx": 0.0, "atr_pct": 0.0}
        plus_di = [(p/atr_s[i])*100 if atr_s[i]>0 else 0.0 for i,p in enumerate(p_s)]
        minus_di = [(m/atr_s[i])*100 if atr_s[i]>0 else 0.0 for i,m in enumerate(m_s)]
        dx = []
        for i in range(min(len(plus_di), len(minus_di))):
            s = plus_di[i] + minus_di[i]; d = abs(plus_di[i]-minus_di[i])
            dx.append((d/s)*100 if s>0 else 0.0)
        adx_s = _wilder(dx)
        adx = adx_s[-1] if adx_s else 0.0
        price = closes[-1]
        atr = atr_s[-1] if atr_s else 0.0
        atr_pct = (atr/price)*100.0 if price>0 else 0.0
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
        # בונים klines בפורמט "דמוי בינאנס" שהסקורינג שלך מצפה לו (close בעמדת index 4)
        k_df = df.reset_index(drop=True).assign(
            open_time=0, close_time=0, qv=0, nTrades=0, taker_base=0, taker_quote=0, x=0
        )
        kl = [
            [int(r.open_time) if "open_time" in k_df.columns else 0,
             float(r.open), float(r.high), float(r.low), float(r.close),
             float(r.volume) if "volume" in k_df.columns else 0.0,
             0, 0, 0, 0, 0, 0]
            for _, r in k_df.iterrows()
        ]
        # חישוב ADX/ATR% מקומי
        adx_atr = _adx_atr_pct_from_df(df, period=14)
        inc_scan_eval()
        res = compute_pretrade_score(kl, adx=float(adx_atr["adx"]), atr_pct=float(adx_atr["atr_pct"])) or {}
        score = float(res.get("score", 0.0))
        features = dict(res.get("features") or {})
        # מטריקות + threshold
        set_last_entry_score(score)
        if ENTRY_SCORE_MIN > 0:
            if score >= ENTRY_SCORE_MIN:
                inc_scan_passed()
            else:
                inc_scan_blocked()
        return {"score": score, "features": features}
    except Exception:
        # לא מפילים את ה־API בגלל תקלת סקורינג
        return {"score": None, "features": None}

# ===================== Endpoints =====================
@router.get("/info", response_model=ScanResponse, summary="Basic Scan Info")
async def scan_info(
    symbol: str = Query(..., description="Symbol e.g. BTCUSDT"),
    interval: str = Query(lambda: ENTRY_SCORE_INTERVAL or "15m"),
    limit: int = Query(200, ge=50, le=200),
) -> ScanResponse:
    try:
        df = await _fetch_klines_async(symbol, interval, limit)
        if df.empty:
            return ScanResponse(ok=False, count_total=1, returned=0, error="no data")

        # אינדיקטורים (אם יש utils.indicators)
        try:
            from utils.indicators import prepare_indicators_for_backtest  # type: ignore
            ind = await asyncio.to_thread(prepare_indicators_for_backtest, df)
            row = {k: (float(v) if pd.notna(v) else None) for k, v in ind.iloc[-1].to_dict().items()}
            indicators = IndicatorSet(**row)
        except Exception:
            indicators = None

        # Score enrichment (מהיר, לוקלי)
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
    interval: str = Query(lambda: ENTRY_SCORE_INTERVAL or "15m"),
    limit: int = Query(200, ge=50, le=200),
) -> ScanResponse:
    # אם לא הועברו סמלים — ננסה מה־WATCHLIST או ברירת מחדל
    if not symbols:
        wl = (os.getenv("WATCHLIST") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,NEARUSDT").split(",")
        syms = [s.strip().upper() for s in wl if s.strip()]
    else:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    syms = [s for s in syms if s]

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





