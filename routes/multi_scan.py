# routes/multi_scan.py
from __future__ import annotations
import asyncio, math
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token(): return None

from utils.top_volume import get_top_volume_symbols
from utils.indicators import prepare_indicators_for_backtest as _prep

import os, requests, pandas as pd

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")
_S = requests.Session()
_S.trust_env = False
_S.headers.update({"User-Agent": "AlgoGPT/2 scan-top-vol"})

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

def _klines(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    try:
        url = f"{FUTURES_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}"
        r = _S.get(url, timeout=7)
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

def _score_row(row: pd.Series) -> Dict[str, Any]:
    # ניקוד מהיר: RSI + מעל/מתחת EMA21 + ADX
    score = 0.0
    side = None
    rsi  = float(row.get("rsi") or 50.0)
    ema  = float(row.get("ema_21") or row.get("close") or 0.0)
    adx  = float(row.get("adx") or 18.0)
    close= float(row.get("close") or 0.0)

    if close and ema:
        if close > ema: score += 1.0
        else: score -= 1.0
    if rsi >= 70: score -= 1.0
    elif rsi <= 30: score += 1.0

    if adx >= 20: score += 0.5

    side = "LONG" if score >= 0.8 else ("SHORT" if score <= -0.8 else None)
    return {"score": round(max(0.0, min(10.0, 5.0 + score*2.0)), 2),
            "side": side, "rsi": rsi, "adx": adx}

async def _scan_one(symbol: str, timeframe: str, limit: int) -> Dict[str, Any]:
    df = await asyncio.to_thread(_klines, symbol, timeframe, limit)
    if df is None or df.empty:
        return {"symbol": symbol, "timeframe": timeframe, "score": 0.0, "note": "no data"}
    ind = await asyncio.to_thread(_prep, df)
    last = ind.tail(1)
    if last.empty:
        return {"symbol": symbol, "timeframe": timeframe, "score": 0.0, "note": "no indicators"}
    row = last.iloc[0]
    s = _score_row(row)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": s["side"],
        "score": s["score"],
        "details": {
            "rsi": s["rsi"],
            "adx": s["adx"],
            "ema_21": float(row.get("ema_21") or 0.0),
            "close": float(row.get("close") or 0.0),
            "atr": float(row.get("atr") or 0.0),
        }
    }

@router.get("/top-volume", summary="Scan top-volume symbols concurrently", operation_id="getScanTopVolume")
async def scan_top_volume(
    market: str = Query("futures", enum=["futures","spot"]),
    quote:  str = Query("USDT"),
    limit:  int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    min_qv: float = Query(0.0, description="Minimal 24h quoteVolume filter"),
    concurrency: int = Query(12, ge=2, le=64),
) -> Dict[str, Any]:
    ok, symbols = get_top_volume_symbols(market=market, quote=quote, limit=limit, min_quote_volume=min_qv)
    if not ok or not symbols:
        return {"ok": False, "count": 0, "signals": [], "note": "no symbols"}

    sem = asyncio.Semaphore(concurrency)
    async def _wrapped(sym: str):
        async with sem:
            return await _scan_one(sym, timeframe, bars)

    tasks = [asyncio.create_task(_wrapped(s)) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        out.append(r)
    return {"ok": True, "count": len(out), "signals": out}










































