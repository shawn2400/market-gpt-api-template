# routes/decision.py
from __future__ import annotations
import asyncio
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, Field, field_validator

from utils.auth import require_api_key
from utils.decision_engine import select_best_trades

router = APIRouter(prefix="/decision", tags=["Analytics"], dependencies=[Depends(require_api_key)])

class BestTradesIn(BaseModel):
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    top_n: int = 5
    diversify_by_symbol: bool = True
    weights: Optional[Dict[str, float]] = None

    @field_validator("top_n")
    @classmethod
    def _cap_top_n(cls, v: int) -> int:
        # מגן רך על עומס: לא יותר מ-50
        return max(1, min(50, int(v)))

@router.post("/best-trades", summary="Select best trades (quality/speed/diversify)")
async def post_best_trades(payload: BestTradesIn = Body(...)) -> Dict[str, Any]:
    selected = await asyncio.to_thread(
        select_best_trades,
        payload.candidates,
        payload.top_n,
        payload.diversify_by_symbol,
        payload.weights,
    )
    return {
        "ok": True,
        "selected": selected,
        "note": f"diversify={payload.diversify_by_symbol}, top_n={payload.top_n}",
    }









