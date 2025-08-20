# routes/ai.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, HTTPException, Query
from pydantic import BaseModel, Field

# --- Auth ---
try:
    from utils.auth import require_bearer_token as _raw_require_bearer
    def require_bearer_token(
        authorization: Optional[str] = None,
        token: Optional[str] = None,
    ):
        return _raw_require_bearer(authorization=authorization, token=token)
except Exception:
    def require_bearer_token():
        return None

# --- Anchor ---
try:
    from utils.anchor import evaluate_anchor, AnchorDecision
except Exception:
    from utils.btc_anchor import evaluate_anchor, AnchorDecision

# --- Quality ---
try:
    from utils.quality import compute_quality
except Exception:
    from utils.quantity_utils import compute_quality

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

# Helper
def _mk_anchor_dict(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

# Endpoint מתוקן עם auth injection
@router.post("/quality", response_model=QualityResponse)
async def post_ai_quality(
    payload: QualityRequest = Body(...),
    _auth=Depends(require_bearer_token),   # 👈 פה ההזרקה האוטומטית של Authorization header
) -> QualityResponse:
    anchor = evaluate_anchor(payload.side)

    sl, tp = payload.sl, payload.tp
    if (sl is None or tp is None) and payload.entry:
        try:
            from utils.ai_analysis import predict_optimal_sl_tp
            try:
                sl, tp = await predict_optimal_sl_tp(payload.symbol, payload.side, payload.entry)
            except TypeError:
                sl, tp = await predict_optimal_sl_tp(payload.symbol, payload.side, entry_price=payload.entry, atr=payload.atr)
        except Exception:
            if payload.side == "LONG":
                sl, tp = payload.entry * 0.997, payload.entry * 1.004
            else:
                sl, tp = payload.entry * 1.003, payload.entry * 0.996

    q = compute_quality(
        symbol=payload.symbol,
        side=payload.side,
        entry=payload.entry,
        sl=sl,
        tp=tp,
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




















