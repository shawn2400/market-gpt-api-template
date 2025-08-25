# routes/topk.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from .context import compute_context
from utils.watchlist_utils import load_watchlist

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

router = APIRouter(prefix="", tags=["TopK"], dependencies=[Depends(require_bearer_token)])

class TopKOut(BaseModel):
    count: int
    symbols: List[str]
    scored: List[Dict[str, Any]]

@router.get("/topk", response_model=TopKOut)
async def topk(
    symbols: Optional[str] = Query(None, description="Comma-separated; default watchlist"),
    interval: str = Query("15m"),
    limit: int = Query(120, ge=60, le=200),
    k: int = Query(12, ge=1, le=50),
):
    if symbols:
        pool = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        wl = load_watchlist()
        pool = [str(it["symbol"]).upper() for it in wl if it.get("symbol")]
        if "BTCUSDT" not in pool:
            pool.insert(0, "BTCUSDT")
    if not pool:
        raise HTTPException(400, "no symbols")

    # משוך הקשר + סקור
    import asyncio
    items = await asyncio.gather(*[compute_context(s, interval, limit, True) for s in pool])
    scored = []
    for ctx in items:
        f = ctx.filters or {}
        scored.append({
            "symbol": ctx.symbol,
            "score": float(f.get("score_light", 0.0)),
            "rr_baseline": f.get("rr_baseline"),
            "trending_up": f.get("trending_up"),
            "trending_down": f.get("trending_down"),
            "volume_spike": f.get("volume_spike"),
            "vol_regime": f.get("vol_regime"),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    pick = [it["symbol"] for it in scored[:k]]
    return TopKOut(count=len(pick), symbols=pick, scored=scored[:k])

