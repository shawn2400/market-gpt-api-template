# routes/decision.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Body
import asyncio

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

try:
    from utils.decision_engine import select_best_trades
except Exception:
    # fallback קטן כדי שלא ניפול ברישום route
    def select_best_trades(candidates, top_n=5, diversify_by_symbol=True):
        out=[]
        seen=set()
        for c in sorted(candidates, key=lambda x: float(x.get("score",0.0)), reverse=True):
            sym=str(c.get("symbol","")).upper()
            if diversify_by_symbol and sym in seen:
                continue
            seen.add(sym)
            out.append(c)
            if len(out)>=int(top_n):
                break
        return out

router = APIRouter(prefix="/decision", tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

@router.post("/best-trades", summary="Select best trades (quality/speed/diversify)", operation_id="postDecisionBestTrades")
async def post_best_trades(payload: Dict[str, Any] = Body(..., embed=False)) -> Dict[str, Any]:
    cands = payload.get("candidates") or []
    top_n = int(payload.get("top_n") or 5)
    diversify = bool(payload.get("diversify_by_symbol", True))
    selected = await asyncio.to_thread(select_best_trades, cands, top_n, diversify)
    return {"ok": True, "selected": selected, "note": f"diversify={diversify}, top_n={top_n}"}




