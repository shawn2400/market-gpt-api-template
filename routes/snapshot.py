# routes/snapshot.py
from __future__ import annotations
import json
from typing import List, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from utils.cache_fallback import lpush, ltrim, get_value
from utils.anchor import evaluate_anchor, AnchorDecision

router = APIRouter(tags=["Anchor"])

# =====================
# Models
# =====================
class AnchorSnapshot(BaseModel):
    ts: int
    side: str
    bias: str
    score: float
    allow: bool


class AnchorHistoryResponse(BaseModel):
    ok: bool = True
    count: int
    items: List[AnchorSnapshot] = Field(default_factory=list)


class AnchorLiveResponse(BaseModel):
    ok: bool = True
    side: str
    decision: Dict[str, Any]


# =====================
# Endpoints
# =====================
@router.get("/anchor/history", response_model=AnchorHistoryResponse)
async def get_anchor_history(limit: int = Query(50, ge=10, le=200)):
    """
    מחזיר את ההיסטוריה האחרונה של Anchor (Redis או fallback).
    """
    key = "anchor:history"
    raw_items = await get_value(key) or []
    if not isinstance(raw_items, list):
        raw_items = []

    items: List[AnchorSnapshot] = []
    for raw in raw_items[:limit]:
        try:
            data = json.loads(raw)
            items.append(AnchorSnapshot(**data))
        except Exception:
            continue

    return AnchorHistoryResponse(count=len(items), items=items)


@router.get("/anchor/live", response_model=AnchorLiveResponse)
async def get_anchor_live(side: str = Query("LONG", regex="^(LONG|SHORT)$")):
    """
    מריץ Evaluate Anchor בזמן אמת ומחזיר תוצאה חיה (לא רק היסטורית).
    """
    dec: AnchorDecision = evaluate_anchor(side)
    return AnchorLiveResponse(
        side=side,
        decision={
            "mode_requested": dec.mode_requested,
            "mode_applied": dec.mode_applied,
            "bias": dec.bias,
            "score": dec.score,
            "allow": dec.allow,
            "severity": dec.severity,
            "reason": dec.reason,
        }
    )







