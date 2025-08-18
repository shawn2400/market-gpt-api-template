# routes/scan_top_volume.py
from __future__ import annotations
import asyncio
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
from fastapi import APIRouter, Query

# בסיסים
FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
SPOT_BASE    = os.getenv("BINANCE_SPOT_HTTP_BASE",    "https://api.binance.com")

_S = requests.Session()
_S.trust_env = False
_S.headers.update({
    "User-Agent": "AlgoGPT/2 scan-topvol",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
})

# ---------- Router 1: /scan ----------
router = APIRouter(prefix="/scan", tags=["Scan"])

# ---------- Router 2: /symbols ----------
router_symbols = APIRouter(prefix="/symbols", tags=["Analytics"])

# === עזר: רשימת סמלים מובילי נפח ===
def _get_top_symbols(market: str, quote: str, limit: int, min_qv: float = 0.0) -> List[str]:
    try:
        from utils.top_volume import get_top_volume_symbols
        ok, symbols = get_top_volume_symbols(
            market=market, quote=quote, limit=limit, min_quote_volume=min_qv
        )
        if ok and symbols:
            return symbols
    except Exception:
        pass

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
            if qv < float(min_qv or 0.0):
                continue
            rows.append((sym, qv))
        rows.sort(key=lambda t: t[1], reverse=True)
        return [s for s, _ in rows[: max(1, int(limit))]]
    except Exception:
        return []

# === /symbols/top-volume (פשוט) ===
@router_symbols.get(
    "/top-volume",
    summary="Top symbols by 24h quote volume (Binance)",
    operation_id="getTopVolumeSymbols"
)
async def symbols_top_volume(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    min_quote_volume: float = Query(0.0, ge=0.0),
) -> Dict[str, Any]:
    symbols = _get_top_symbols(market, quote, limit, min_quote_volume)
    return {
        "ok": True,
        "market": market,
        "quote": quote.upper(),
        "limit": limit,
        "symbols": symbols,
    }

# === /scan/top-volume (מורחב – כולל ניקוד טרנד בסיסי) ===
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

@router.get(
    "/top-volume",
    summary="Scan top-volume symbols concurrently (extended)",
    operation_id="getScanTopVolume",
)
async def scan_top_volume(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
    min_adx: float = Query(20.0, ge=5.0, le=60.0),
    ema_fast: int = Query(21, ge=3, le=200),
    ema_slow: int = Query(50, ge=5, le=400),
    adx_len: int = Query(14, ge=5, le=50),
    concurrency: int = Query(16, ge=2, le=64),
) -> Dict[str, Any]:
    # שלב 1: סמלים
    symbols = _get_top_symbols(market, quote, limit)
    if not symbols:
        return {"ok": True, "count": 0, "signals": []}

    # שלב 2: משיכת נתונים + ניקוד בסיסי
    from utils.indicators_ext import add_extended_indicators, extended_score_last_row

    sem = asyncio.Semaphore(concurrency)
    results: List[Dict[str, Any]] = []

    async def _process(sym: str):
        async with sem:
            df = await asyncio.to_thread(_klines, sym, timeframe, bars, market)
            if df is None or df.empty:
                return
            df2 = add_extended_indicators(df, ema_fast=ema_fast, ema_slow=ema_slow, adx_len=adx_len)
            if df2.empty:
                return
            row = df2.iloc[-1]
            score, side, conf, reason = extended_score_last_row(row)
            if trending_only and not bool(row.get("trending") is True):
                return
            if float(row.get("adx") or 0.0) < float(min_adx):
                return
            results.append({
                "symbol": sym,
                "timeframe": timeframe,
                "side": side,
                "score": float(score),
                "confidence": int(conf),
                "note": reason,
                "details": {
                    "adx": float(row.get("adx") or 0.0),
                    "ema_fast": float(row.get("ema_fast") or 0.0),
                    "ema_slow": float(row.get("ema_slow") or 0.0),
                    "close": float(row.get("close") or 0.0),
                }
            })

    await asyncio.gather(*[_process(s) for s in symbols])

    # מיון לפי score
    results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return {"ok": True, "count": len(results), "signals": results}









