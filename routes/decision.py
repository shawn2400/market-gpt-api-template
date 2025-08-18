# routes/decision.py
from __future__ import annotations
from typing import Dict, Any
from fastapi import APIRouter, Depends, Body

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        return None

from utils.decision_engine import select_best_trades

router = APIRouter(prefix="/decision", tags=["Analytics"], dependencies=[Depends(require_bearer_token)])

@router.post("/best-trades", summary="Select best trades (quality/speed/diversify)", operation_id="postDecisionBestTrades")
async def post_best_trades(payload: Dict[str, Any] = Body(..., embed=False)) -> Dict[str, Any]:
    import asyncio
    cands = payload.get("candidates") or []
    top_n = int(payload.get("top_n") or 5)
    diversify = bool(payload.get("diversify_by_symbol", True))
    selected = await asyncio.to_thread(select_best_trades, cands, top_n, diversify)
    return {"ok": True, "selected": selected, "note": f"diversify={diversify}, top_n={top_n}"}


