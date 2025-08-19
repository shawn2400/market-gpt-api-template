# routes/ai.py
from __future__ import annotations

from typing import Optional, Literal, Dict, Any
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, Field

try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

try:
    from utils.anchor import evaluate_anchor, AnchorDecision  # shim
except Exception:
    from utils.btc_anchor import evaluate_anchor, AnchorDecision  # type: ignore

try:
    from utils.quality import compute_quality  # shim name
except Exception:
    from utils.quantity_utils import compute_quality  # type: ignore

router = APIRouter(
    tags=["AI"],
    dependencies=[Depends(require_bearer_token)],
)

Side = Literal["LONG", "SHORT"]

class QualityRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
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

async def _anchor_dep(payload: QualityRequest = Body(...)) -> AnchorDecision:
    return evaluate_anchor(payload.side)

@router.post("/quality", response_model=QualityResponse, operation_id="postAiQuality")
async def post_ai_quality(
    payload: QualityRequest = Body(...),
    anchor: AnchorDecision = Depends(_anchor_dep),
) -> QualityResponse:
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
        quality_score=q["quality_score"],
        success_pct=q["success_pct"],
        components=q["components"],
        anchor={
            "mode_requested": anchor.mode_requested,
            "mode_applied": anchor.mode_applied,
            "bias": anchor.bias,
            "score": anchor.score,
            "severity": anchor.severity,
            "reason": anchor.reason,
        },
    )


















