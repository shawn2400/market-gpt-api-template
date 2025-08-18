# routes/scan_top_volume.py
from __future__ import annotations
import asyncio
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from fastapi import APIRouter, Query

from utils.get_klines import aget_klines
from utils.indicators_ext import add_extended_indicators, extended_score_last_row
from utils.top_volume import get_top_volume_symbols

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
SPOT_BASE    = os.getenv("BINANCE_SPOT_HTTP_BASE",    "https://api.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 scan-topvol", "Accept": "application/json"})

# רואוטר לסריקה
router = APIRouter(prefix="/scan", tags=["Scan"])
# רואוטר נוסף לנתיב טופ-ווליום הכללי (ללא prefix)
router_symbols = APIRouter(tags=["Analytics"])

def _fallback_top_symbols(market: str, quote: str, limit: int) -> List[str]:
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

async def _score_symbol(symbol: str, timeframe: str, bars: int, market: str,
                        ema_fast: int, ema_slow: int, adx_len: int,
                        st_period: int, st_factor: float,
                        ich_conv: int, ich_base: int, ich_span_b: int,
                        ms_lookback: int, ms_pivot_span: int,
                        min_adx: float, trending_only: bool) -> Optional[Dict[str, Any]]:
    df = await aget_klines(symbol, timeframe, limit=bars, market_type=market)
    if df is None or df.empty:
        return None

    df2 = add_extended_indicators(df, ema_fast=ema_fast, ema_slow=ema_slow,
                                  adx_len=adx_len, st_period=st_period, st_factor=st_factor,
                                  ichimoku_conv=ich_conv, ichimoku_base=ich_base, ichimoku_span_b=ich_span_b,
                                  ms_lookback=ms_lookback, ms_pivot_span=ms_pivot_span)
    if df2.empty:
        return None

    last = df2.iloc[-1]
    adx_val = float(last.get("adx") or 0.0)
    if trending_only and adx_val < float(min_adx):
        return None

    score, side, conf, reason = extended_score_last_row(last)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "score": float(round(score, 2)),
        "confidence": int(conf),
        "note": reason,
        "details": {
            "adx": adx_val,
            "ema_fast": float(last.get("ema_fast") or 0.0),
            "ema_slow": float(last.get("ema_slow") or 0.0),
            "close": float(last.get("close") or 0.0),
            "trending": bool(last.get("trending") is True),
        },
    }

@router.get("/top-volume", operation_id="getScanTopVolume")
async def get_scan_top_volume(
    market: str = Query("futures", regex="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
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
):
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit)
    if not ok or not symbols:
        symbols = _fallback_top_symbols(market, quote, limit)

    tasks = [
        _score_symbol(
            s, timeframe, bars, market,
            ema_fast, ema_slow, adx_len,
            st_period, st_factor,
            ich_conv, ich_base, ich_span_b,
            ms_lookback, ms_pivot_span,
            min_adx, trending_only
        )
        for s in symbols
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    signals: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, dict):
            signals.append(r)

    signals.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return {"ok": True, "count": len(signals), "signals": signals}

@router_symbols.get("/symbols/top-volume", operation_id="getTopVolumeSymbols")
async def get_symbols_top_volume(
    market: str = Query("futures", regex="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0, ge=0.0),
):
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=min_quote_volume)
    if not ok:
        symbols = _fallback_top_symbols(market, quote, limit)
    return {
        "ok": True,
        "market": market,
        "quote": quote,
        "limit": limit,
        "symbols": symbols,
    }








