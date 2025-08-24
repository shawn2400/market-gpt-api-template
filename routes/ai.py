# routes/ai.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality import compute_quality

router = APIRouter(tags=["AI"])
Side = Literal["LONG", "SHORT"]

class QualityRequest(BaseModel):
    symbol: str
    side: Side
    entry: Optional[float] = Field(None, gt=0)
    sl: Optional[float] = Field(None, gt=0)
    tp: Optional[float] = Field(None, gt=0)
    leverage: int = Field(10, ge=1, le=125)
    budget: float = Field(100.0, gt=0)
    atr: Optional[float] = Field(None, gt=0)

class QualityResponse(BaseModel):
    quality_score: float
    success_pct: float
    anchor: Dict[str, Any]
    components: Dict[str, Any]

def _mk_anchor_dict(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

@router.get("/health")
async def ai_health():
    import os
    ok = bool(os.getenv("OPENAI_API_KEY"))
    return {
        "ok": ok,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "reason": None if ok else "Missing OPENAI_API_KEY",
    }

@router.post("/quality", response_model=QualityResponse)
async def post_ai_quality(
    payload: QualityRequest = Body(...),
    _auth=Depends(require_api_key)
) -> QualityResponse:
    anchor = evaluate_anchor(payload.side)
    q = compute_quality(
        symbol=payload.symbol,
        side=payload.side,
        entry=payload.entry,
        sl=payload.sl,
        tp=payload.tp,
        leverage=payload.leverage,
        budget=payload.budget,
        anchor=anchor,
        atr=payload.atr,
    )
    return QualityResponse(
        quality_score=float(q.get("quality_score", 0.0)),
        success_pct=float(q.get("success_pct", 0.0)),
        components=q.get("components") or {},
        anchor=_mk_anchor_dict(anchor),
    )






















