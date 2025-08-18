# routes/multi_scan.py
from __future__ import annotations
import os
import asyncio
from typing import List, Dict, Any, Optional
import pandas as pd
import requests
from fastapi import APIRouter, Depends, Query, HTTPException

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():  # fallback – מחייב Authorization
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.top_volume import get_top_volume_symbols
from utils.indicators import prepare_indicators_for_backtest as _prep_base
from utils.indicators_ext import add_extended_indicators, extended_score_last_row

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 scan-top-vol+ext",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

def _klines(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    try:
        url = f"{FUTURES_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}"
        r = _S.get(url, timeout=8)
        if r.status_code != 200:
            return None
        arr = r.json()
        df = pd.DataFrame(arr, columns=[
            "openTime","open","high","low","close","volume","closeTime","qv","nTrades","takerBase","takerQuote","x"
        ])
        for c in ("open","high","low","close","volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["timestamp"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        return df[["timestamp","open","high","low","close","volume"]]
    except Exception:
        return None

async def _scan_one(
    symbol: str, timeframe: str, bars: int,
    *, ema_fast: int, ema_slow: int, adx_len: int,
    st_period: int, st_factor: float,
    ich_conv: int, ich_base: int, ich_span_b: int,
    ms_lookback: int, ms_pivot_span: int,
    min_adx: float, trending_only: bool
) -> Optional[Dict[str, Any]]:
    df = await asyncio.to_thread(_klines, symbol, timeframe, bars)
    if df is None or df.empty:
        return {"symbol": symbol, "timeframe": timeframe, "score": 0.0, "note": "no data"}

    base = await asyncio.to_thread(_prep_base, df)
    ext = await asyncio.to_thread(
        add_extended_indicators, base,
        ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len,
        st_period=st_period, st_factor=st_factor,
        ichimoku_conv=ich_conv, ichimoku_base=ich_base, ichimoku_span_b=ich_span_b,
        ms_lookback=ms_lookback, ms_pivot_span=ms_pivot_span
    )
    last = ext.tail(1)
    if last.empty:
        return {"symbol": symbol, "timeframe": timeframe, "score": 0.0, "note": "no indicators"}

    row = last.iloc[0]
    adx = float(row.get("adx") or 0.0)
    trend_dir = str(row.get("trend_dir") or "FLAT")
    trending = bool(row.get("trending") is True and adx >= float(min_adx or 0.0))

    if trending_only and not trending:
        return None

    score, side, conf, reason = extended_score_last_row(row)
    if not trending:
        score = round(max(0.0, score - 0.8), 2)
        reason = (reason + " non-trend")[:140]

    details = {
        "trend_dir": trend_dir,
        "trending": trending,
        "adx": float(row.get("adx") or 0.0),
        "ema_fast": float(row.get("ema_fast") or 0.0),
        "ema_slow": float(row.get("ema_slow") or 0.0),
        "atr": float(row.get("atr") or 0.0),
        "ichimoku_state": str(row.get("ichimoku_state") or ""),
        "stoch_k": float(row.get("stoch_k") or 0.0),
        "stoch_d": float(row.get("stoch_d") or 0.0),
        "ms_label": str(row.get("ms_label") or ""),
        "ms_trend": str(row.get("ms_trend") or ""),
        "supertrend": float(row.get("supertrend") or 0.0),
        "close": float(row.get("close") or 0.0),
    }
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "score": score,
        "note": reason,
        "details": details,
    }

@router.get(
    "/top-volume",
    summary="Scan top-volume symbols concurrently (extended)",
    operation_id="getScanTopVolume",
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

    ms_lookback: int = Query(5, ge=2, le=20),
    ms_pivot_span: int = Query(3, ge=1, le=10),

    concurrency: int = Query(16, ge=2, le=64),
) -> Dict[str, Any]:
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=0.0)
    if not ok or not symbols:
        return {"ok": False, "count": 0, "signals": [], "note": "no symbols"}

    sem = asyncio.Semaphore(concurrency)
    async def _wrapped(sym: str):
        async with sem:
            return await _scan_one(
                sym, timeframe, bars,
                ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len,
                st_period=st_period, st_factor=st_factor,
                ich_conv=ich_conv, ich_base=ich_base, ich_span_b=ich_span_b,
                ms_lookback=ms_lookback, ms_pivot_span=ms_pivot_span,
                min_adx=min_adx, trending_only=trending_only
            )

    tasks = [asyncio.create_task(_wrapped(s)) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        out.append(r)

    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return {"ok": True, "count": len(out), "signals": out}














































