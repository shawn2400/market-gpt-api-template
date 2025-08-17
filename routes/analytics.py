# routes/analytics.py
from __future__ import annotations
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query, Body

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.correlation import compute_correlation
from utils.macro import macro_snapshot
from utils.sentiment import summarize_sentiment
from utils.time_to_target import eta_by_atr

router = APIRouter(dependencies=[Depends(require_bearer_token)], tags=["Analytics"])

@router.get("/analytics/correlation", summary="Correlation ALT to BTC", operation_id="getCorrelation")
async def get_correlation(
    symbols: List[str] = Query(..., description="Comma-separated or repeated, e.g. ETHUSDT,BNBUSDT", alias="symbols"),
    ref_symbol: str = Query("BTCUSDT"),
    timeframe: str = Query("15m"),
    window: int = Query(200, ge=50, le=2000),
) -> Dict[str, Any]:
    # FastAPI יפרק רשימה גם מ־?symbols=ETHUSDT,BNBUSDT
    symbols = [s.strip().upper() for s in (symbols or []) if s.strip()]
    items = await _to_thread(compute_correlation, symbols, ref_symbol, timeframe, window)
    return {"ok": True, "items": items}

async def _to_thread(fn, *a, **kw):
    import asyncio
    return await asyncio.to_thread(fn, *a, **kw)

@router.get("/analytics/macro", summary="Macro snapshot (DXY/NDX/SPX/FG/BTC.D)", operation_id="getMacro")
async def get_macro():
    snap = await _to_thread(macro_snapshot)
    return snap

@router.get("/sentiment/summary", summary="Sentiment summary (-100..100)", operation_id="getSentiment")
async def get_sentiment():
    return await _to_thread(summarize_sentiment)

class EtaReq(BaseException):
    ...

@router.post("/eta/time-to-target", summary="ETA to TP/SL by ATR speed", operation_id="postEtaToTarget")
async def post_eta_to_target(
    payload: Dict[str, Any] = Body(..., embed=False)
):
    entry = float(payload.get("entry"))
    tp    = float(payload.get("tp"))
    sl    = float(payload.get("sl"))
    atr   = float(payload.get("atr"))
    tf    = str(payload.get("timeframe") or "15m")
    return eta_by_atr(entry=entry, tp=tp, sl=sl, atr=atr, timeframe=tf)
