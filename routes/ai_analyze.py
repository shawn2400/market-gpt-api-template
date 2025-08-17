# routes/ai_analyze.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

# Auth (fallback אם צריך)
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

# Anchor + quality
try:
    from utils.anchor import evaluate_anchor, AnchorDecision
except Exception:
    from utils.btc_anchor import evaluate_anchor, AnchorDecision  # type: ignore

from utils.quality import compute_quality

Side = Literal["LONG", "SHORT"]
router = APIRouter(
    tags=["AI"],
    dependencies=[Depends(require_bearer_token)],
)

class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    side: Side
    entry: Optional[float] = Field(None, gt=0)
    sl: Optional[float] = Field(None, gt=0)
    tp: Optional[float] = Field(None, gt=0)
    leverage: int = Field(10, ge=1, le=125)
    budget: float = Field(100.0, gt=0)
    atr: Optional[float] = Field(None, gt=0)

class AnalyzeResponse(BaseModel):
    quality_score: float
    success_pct: float
    anchor: Dict[str, Any]
    components: Dict[str, Any]

async def _anchor_dep(payload: AnalyzeRequest = Body(...)) -> AnchorDecision:
    return evaluate_anchor(payload.side)

@router.post("/ai-analyze", response_model=AnalyzeResponse, operation_id="postAiAnalyze")
async def post_ai_analyze(
    payload: AnalyzeRequest = Body(...),
    anchor: AnchorDecision = Depends(_anchor_dep),
) -> AnalyzeResponse:
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
    return AnalyzeResponse(
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
