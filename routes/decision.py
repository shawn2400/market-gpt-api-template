# routes/decision.py
from __future__ import annotations
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, Depends, Body

from utils.auth import require_api_key
from utils.decision_engine import select_best_trades

router = APIRouter(prefix="/decision", tags=["Analytics"], dependencies=[Depends(require_api_key)])

@router.post("/best-trades", summary="Select best trades (quality/speed/diversify)")
async def post_best_trades(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    cands = payload.get("candidates") or []
    top_n = int(payload.get("top_n") or 5)
    diversify = bool(payload.get("diversify_by_symbol", True))
    selected = await asyncio.to_thread(select_best_trades, cands, top_n, diversify)
    return {"ok": True, "selected": selected, "note": f"diversify={diversify}, top_n={top_n}"}





