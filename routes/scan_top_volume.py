# routes/scan_top_volume.py
from __future__ import annotations
import os, asyncio
from typing import Dict, Any, List
import pandas as pd
import requests
from fastapi import APIRouter, Depends, Query

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.cache import aget_or_set
from utils.top_volume import get_top_volume_symbols
from utils.indicators_ext import enrich_ext, market_structure

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# TTLs מה־ENV (אפשר לכוונן בלי לגעת בקוד)
TV_LIST_TTL    = float(os.getenv("SCAN_TOP_VOLUME_TTL", "60"))   # cache לרשימת Top Volume
TV_KLINES_TTL  = float(os.getenv("SCAN_TOP_VOLUME_KLINES_TTL", "30"))  # cache ל־klines
ENV_MIN_QV     = float(os.getenv("TOP_VOLUME_MIN_QV", "0"))

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

def _fetch_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    url = f"{FUTURES_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}"
    r = requests.get(url, timeout=8)
    r.raise_for_status()
    arr = r.json()
    df = pd.DataFrame(arr, columns=[
        "openTime","open","high","low","close","volume","closeTime","qv","nTrades","takerBase","takerQuote","x"
    ])
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
    return df[["timestamp","open","high","low","close","volume"]]

def _score_signal(d: pd.DataFrame) -> Dict[str, Any]:
    last = d.tail(1).iloc[0]
    score = 0.0
    note = []
    if last["ema_fast"] > last["ema_slow"]:
        score += 2.0; note.append("ema_cross=up")
    else:
        score += 0.5; note.append("ema_cross=down")
    if last["adx"] >= 25:
        score += 2.0; note.append("adx≥25")
    elif last["adx"] >= 18:
        score += 1.0; note.append("adx≥18")
    if bool(last["st_trend_up"]):
        score += 1.5; note.append("st=up")
    if bool(last["ich_bull"]):
        score += 1.5; note.append("ich=bull")
    try:
        if last.get("stochrsi_k", 1.0) > last.get("stochrsi_d", 1.0) and last.get("stochrsi_k", 1.0) < 0.8:
            score += 1.0; note.append("stochrsi=buy")
    except Exception:
        pass
    return {"score": min(10.0, round(score * 1.6, 2)), "note": ", ".join(note)}

async def _scan_one(symbol: str, timeframe: str, bars: int,
                    ema_fast:int, ema_slow:int, adx_len:int,
                    st_period:int, st_factor:float,
                    ich_conv:int, ich_base:int, ich_span_b:int,
                    ms_lookback:int, ms_pivot_span:int) -> Dict[str, Any]:
    # cache ל־klines לפי (symbol, timeframe, bars)
    kkey = f"kl|{symbol}|{timeframe}|{bars}"
    async def load_kl():
        return await asyncio.to_thread(_fetch_klines, symbol, timeframe, bars)
    df = await aget_or_set(kkey, TV_KLINES_TTL, load_kl)

    ext = await asyncio.to_thread(enrich_ext, df,
                                  ema_fast=ema_fast, ema_slow=ema_slow,
                                  adx_len=adx_len, st_period=st_period, st_factor=st_factor,
                                  ich_conv=ich_conv, ich_base=ich_base, ich_span_b=ich_span_b)
    if ext.empty:
        return {"symbol": symbol, "timeframe": timeframe, "score": 0.0, "note": "no-data"}
    ms = market_structure(ext, lookback=ms_lookback, pivot_span=ms_pivot_span)
    s = _score_signal(ext)
    direction = "LONG" if s["score"] >= 5.0 and ext["ema_fast"].iat[-1] > ext["ema_slow"].iat[-1] else (
                "SHORT" if s["score"] >= 5.0 and ext["ema_fast"].iat[-1] < ext["ema_slow"].iat[-1] else None)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "score": s["score"],
        "note": s["note"],
        "details": {
            "adx": float(ext["adx"].iat[-1]),
            "ema_fast": float(ext["ema_fast"].iat[-1]),
            "ema_slow": float(ext["ema_slow"].iat[-1]),
            "supertrend_up": bool(ext["st_trend_up"].iat[-1]),
            "ich_bull": bool(ext["ich_bull"].iat[-1]),
            "stochrsi_k": float(ext["stochrsi_k"].iat[-1]) if "stochrsi_k" in ext else None,
            "market_structure": ms.get("ms"),
        },
        "side": direction,
    }

@router.get("/top-volume", summary="Scan top-volume symbols concurrently (extended)", operation_id="getScanTopVolume")
async def get_scan_top_volume(
    market: str = Query("futures", enum=["futures","spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
    min_quote_volume: float | None = Query(None, ge=0.0, description="Override ENV TOP_VOLUME_MIN_QV"),
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
):
    eff_min_qv = ENV_MIN_QV if (min_quote_volume is None) else float(min_quote_volume)

    # cache לרשימת ה־Top Volume
    list_key = f"topvol|{market}|{quote}|{limit}|{eff_min_qv}"
    async def load_syms():
        return await asyncio.to_thread(get_top_volume_symbols, market, quote, limit, eff_min_qv)
    ok, syms = await aget_or_set(list_key, TV_LIST_TTL, load_syms)

    if not ok or not syms:
        return {"ok": False, "count": 0, "signals": []}

    sem = asyncio.Semaphore(concurrency)
    async def worker(sym: str):
        async with sem:
            return await _scan_one(sym, timeframe, bars, ema_fast, ema_slow, adx_len,
                                   st_period, st_factor, ich_conv, ich_base, ich_span_b,
                                   ms_lookback, ms_pivot_span)

    results = await asyncio.gather(*[worker(s) for s in syms], return_exceptions=False)

    if trending_only:
        filtered: List[Dict[str, Any]] = []
        for r in results:
            adx_ok = r.get("details", {}).get("adx", 0.0) >= min_adx
            st_ok  = r.get("details", {}).get("supertrend_up", False)
            ema_ok = r.get("details", {}).get("ema_fast", 0.0) > r.get("details", {}).get("ema_slow", 0.0)
            ich_ok = r.get("details", {}).get("ich_bull", False)
            if (adx_ok and (st_ok or ich_ok) and ema_ok) or (adx_ok and r.get("side") is not None):
                filtered.append(r)
        results = filtered

    results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return {"ok": True, "count": len(results), "signals": results}

