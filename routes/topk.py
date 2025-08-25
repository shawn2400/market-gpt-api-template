# routes/topk.py
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import math, os, asyncio

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from .context import get_context  # משתמשים בלוגיקת ההקשר שחישבנו

from utils.watchlist_utils import load_watchlist

router = APIRouter(prefix="", tags=["TopK"], dependencies=[Depends(require_bearer_token)])

class TopKOut(BaseModel):
    count: int
    symbols: List[str]
    scored: List[Dict[str, Any]]

def _score_ctx(ctx: Dict[str, Any]) -> float:
    # ניקוד פשוט, שקוף ומהיר
    f = ctx.get("filters", {})
    s = 0.0
    s += 1.5 if f.get("trending_up") else 0.0
    s += 1.0 if f.get("volume_spike") else 0.0
    s += 0.5 if f.get("obv_z_ge_1") else 0.0
    s += 0.3 if (ctx.get("rsi") and 40 <= ctx["rsi"] <= 65) else 0.0
    s -= 0.7 if f.get("overbought") else 0.0
    s -= 0.5 if f.get("trending_down") else 0.0
    return s

@router.get("/topk", response_model=TopKOut)
async def topk(
    symbols: Optional[str] = Query(None, description="Comma-separated, default from watchlist"),
    interval: str = Query("15m"),
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

    # משיכת הקשר במקביל לכל הסמלים
    async def one(sym: str):
        try:
            ctx = await get_context(request=None, symbol=sym, interval=interval, limit=120, include_filters=True)  # type: ignore
            return sym, ctx
        except Exception:
            return sym, None

    results = await asyncio.gather(*[one(s) for s in pool])
    scored = []
    for sym, ctx in results:
        if ctx:
            score = _score_ctx(ctx)  # ציון “חום”
            scored.append({"symbol": sym, "score": round(score, 3), "ctx": ctx})
    scored.sort(key=lambda x: x["score"], reverse=True)
    pick = [it["symbol"] for it in scored[:k]]
    return TopKOut(count=len(pick), symbols=pick, scored=scored[:k])
