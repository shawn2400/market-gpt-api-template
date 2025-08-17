# routes/analytics.py
from __future__ import annotations
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query, Body
import asyncio

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.cache import aget_or_set
from utils.correlation import compute_correlation
from utils.macro import macro_snapshot
from utils.sentiment import summarize_sentiment
from utils.time_to_target import eta_by_atr
import os

TTL_MACRO = float(os.getenv("CACHE_TTL_MACRO", "300"))     # 5m
TTL_CORR  = float(os.getenv("CACHE_TTL_CORR",  "120"))     # 2m
TTL_SENT  = float(os.getenv("CACHE_TTL_SENT",  "90"))      # 1.5m

router = APIRouter(dependencies=[Depends(require_bearer_token)], tags=["Analytics"])

async def _to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)

@router.get("/analytics/correlation", summary="Correlation ALT to BTC", operation_id="getCorrelation")
async def get_correlation(
    symbols: List[str] = Query(..., alias="symbols", description="Comma-separated or repeated"),
    ref_symbol: str = Query("BTCUSDT"),
    timeframe: str = Query("15m"),
    window: int = Query(200, ge=50, le=2000),
) -> Dict[str, Any]:
    symbols = [s.strip().upper() for s in (symbols or []) if s.strip()]
    key = f"corr|{','.join(symbols)}|{ref_symbol}|{timeframe}|{window}"
    async def load():
        return await _to_thread(compute_correlation, symbols, ref_symbol, timeframe, window)
    items = await aget_or_set(key, TTL_CORR, load)
    return {"ok": True, "items": items}

@router.get("/analytics/macro", summary="Macro snapshot (DXY/NDX/SPX/FG/BTC.D)", operation_id="getMacro")
async def get_macro():
    async def load(): 
        return await _to_thread(macro_snapshot)
    snap = await aget_or_set("macro|snapshot", TTL_MACRO, load)
    return snap

@router.get("/sentiment/summary", summary="Sentiment summary (-100..100)", operation_id="getSentiment")
async def get_sentiment():
    async def load():
        return await _to_thread(summarize_sentiment)
    return await aget_or_set("sentiment|summary", TTL_SENT, load)

@router.post("/eta/time-to-target", summary="ETA to TP/SL by ATR speed", operation_id="postEtaToTarget")
async def post_eta_to_target(payload: Dict[str, Any] = Body(..., embed=False)):
    entry = float(payload.get("entry"))
    tp    = float(payload.get("tp"))
    sl    = float(payload.get("sl"))
    atr   = float(payload.get("atr"))
    tf    = str(payload.get("timeframe") or "15m")
    return eta_by_atr(entry=entry, tp=tp, sl=sl, atr=atr, timeframe=tf)

