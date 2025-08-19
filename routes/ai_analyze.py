# routes/ai_analyze.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, Field

# --- Auth (קשיח) ---
try:
    from utils.auth import require_bearer_token as _raw_require_bearer  # type: ignore
    def require_bearer_token():
        try:
            return _raw_require_bearer()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized")
except Exception:
    def require_bearer_token():
        return None

# --- Anchor (shim→fallback) ---
try:
    from utils.anchor import evaluate_anchor, AnchorDecision  # type: ignore
except Exception:
    from utils.btc_anchor import evaluate_anchor, AnchorDecision  # type: ignore

# --- Quality (shim→fallback) ---
try:
    from utils.quality import compute_quality  # type: ignore
except Exception:
    from utils.quantity_utils import compute_quality  # type: ignore

router = APIRouter(tags=["AI"], dependencies=[Depends(require_bearer_token)])

Side = Literal["LONG", "SHORT"]

class AiAnalyzeRequest(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"])
    side: Side
    entry: Optional[float] = Field(None, gt=0)
    sl: Optional[float] = Field(None, gt=0)
    tp: Optional[float] = Field(None, gt=0)
    leverage: int = Field(10, ge=1, le=125)
    budget: float = Field(100.0, gt=0)
    atr: Optional[float] = Field(None, gt=0)

class AiAnalyzeResponse(BaseModel):
    quality_score: float
    success_pct: float
    anchor: Dict[str, Any]
    components: Dict[str, Any]
    suggested: Dict[str, Any] | None = None  # כולל SL/TP מוצעים אם חושבו

async def _maybe_predict_sltp(symbol: str, side: Side, entry: Optional[float], atr: Optional[float]) -> Dict[str, float] | None:
    """
    ננסה כמה מסלולים להפקת SL/TP. לא זורק חריגות — מחזיר None כשאין.
    """
    if not entry:
        return None
    # 1) utils.ai_analysis.predict_optimal_sl_tp (מגוון חתימות)
    try:
        from utils.ai_analysis import predict_optimal_sl_tp  # type: ignore
        try:
            sl, tp = await predict_optimal_sl_tp(symbol, side, entry)  # חתימה ישנה
            return {"sl": float(sl), "tp": float(tp)}
        except TypeError:
            sl, tp = await predict_optimal_sl_tp(symbol, side, entry_price=entry, atr=atr)  # חתימה חדשה
            return {"sl": float(sl), "tp": float(tp)}
    except Exception:
        pass
    # 2) utils.sl_tp_utils.suggest_sltp (אם קיים)
    try:
        from utils.sl_tp_utils import suggest_sltp  # type: ignore
        res = suggest_sltp(symbol=symbol, direction=side, entry=float(entry), atr=atr)
        sl, tp = float(res["sl"]), float(res["tp"])
        return {"sl": sl, "tp": tp}
    except Exception:
        pass
    # 3) פולבק שמרני
    try:
        if side == "LONG":
            return {"sl": round(entry * 0.997, 6), "tp": round(entry * 1.004, 6)}
        else:
            return {"sl": round(entry * 1.003, 6), "tp": round(entry * 0.996, 6)}
    except Exception:
        return None

def _mk_anchor_dict(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

@router.post("/ai-analyze", response_model=AiAnalyzeResponse, operation_id="postAiAnalyze")
async def post_ai_analyze(payload: AiAnalyzeRequest = Body(...)) -> AiAnalyzeResponse:
    # הערכת עוגן (anchor) לפי הצד
    anchor = evaluate_anchor(payload.side)

    # אם חסר SL/TP ונמסר entry → ננסה לחזות
    suggested = None
    sl = payload.sl
    tp = payload.tp
    if (sl is None or tp is None) and payload.entry:
        s = await _maybe_predict_sltp(payload.symbol, payload.side, payload.entry, payload.atr)
        if s:
            sl = sl if sl is not None else s["sl"]
            tp = tp if tp is not None else s["tp"]
            suggested = {"sl": float(sl), "tp": float(tp), "note": "auto"}

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

    return AiAnalyzeResponse(
        quality_score=float(q.get("quality_score", 0.0)),
        success_pct=float(q.get("success_pct", 0.0)),
        components=q.get("components") or {},
        anchor=_mk_anchor_dict(anchor),
        suggested=suggested,
    )

