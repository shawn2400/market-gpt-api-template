# routes/ai.py
from __future__ import annotations

from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, HTTPException, Query, status
from pydantic import BaseModel, Field

# --- Auth (קשיח: מחזיר 401 במקום להפיל שרת) ---
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
    # מצב פיתוח ללא אימות
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

# =========================
# Models
# =========================
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

class AiManualScanItem(BaseModel):
    symbol: str
    market: Optional[str] = Field(None, example="futures")
    interval: Optional[str] = Field(None, example="15m")
    frames: List[str] = Field(default_factory=list)
    trend: Optional[Literal["UP", "DOWN"]] = None
    direction: Optional[Side] = None
    rsi: Optional[float] = None
    adx: Optional[float] = None
    volume: Optional[float] = None
    quality_score: Optional[float] = Field(None, ge=0, le=10)
    signal: Optional[Literal["BUY", "SELL", "HOLD"]] = None
    confidence: Optional[int] = Field(None, ge=0, le=100)
    reason: Optional[str] = None
    close: Optional[float] = None
    atr: Optional[float] = None

class AiManualScanResponse(BaseModel):
    symbol: str
    results: AiManualScanItem

# =========================
# Helpers
# =========================
def _mk_anchor_dict(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

async def _maybe_predict_sltp(symbol: str, side: Side, entry: Optional[float], atr: Optional[float]) -> Dict[str, float] | None:
    """
    מנסה לחשב SL/TP ממספר מקורות. לא זורק חריגות.
    """
    if not entry:
        return None
    # 1) utils.ai_analysis.predict_optimal_sl_tp (תומך בחתימות שונות)
    try:
        from utils.ai_analysis import predict_optimal_sl_tp  # type: ignore
        try:
            sl, tp = await predict_optimal_sl_tp(symbol, side, entry)  # חתימה ישנה
        except TypeError:
            sl, tp = await predict_optimal_sl_tp(symbol, side, entry_price=entry, atr=atr)  # חתימה חדשה
        return {"sl": float(sl), "tp": float(tp)}
    except Exception:
        pass
    # 2) utils.sl_tp_utils.suggest_sltp (אם זמין)
    try:
        from utils.sl_tp_utils import suggest_sltp  # type: ignore
        res = suggest_sltp(symbol=symbol, direction=side, entry=float(entry), atr=atr)
        return {"sl": float(res["sl"]), "tp": float(res["tp"])}
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

# =========================
# Endpoints
# =========================
@router.post(
    "/quality",
    response_model=QualityResponse,
    operation_id="postAiQuality",
)
async def post_ai_quality(payload: QualityRequest = Body(...)) -> QualityResponse:
    """
    מחשב ציון איכות לטרייד בהתחשב ב-anchor, SL/TP (כולל השלמה אוטומטית אם חסר), ועוד.
    """
    anchor = evaluate_anchor(payload.side)

    # השלמת SL/TP אם אפשר (על בסיס entry)
    sl, tp = payload.sl, payload.tp
    if (sl is None or tp is None) and payload.entry:
        s = await _maybe_predict_sltp(payload.symbol, payload.side, payload.entry, payload.atr)
        if s:
            sl = sl if sl is not None else s["sl"]
            tp = tp if tp is not None else s["tp"]

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

@router.get(
    "/manual-scan",
    response_model=AiManualScanResponse,
    operation_id="getAiManualScan",
)
async def get_ai_manual_scan(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    market: str = Query("futures"),
    interval: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
) -> AiManualScanResponse:
    """
    ניתוח סימבול בודד. אם מודול הסורק לא קיים/נכשל — מוחזר אובייקט ניטרלי עם reason.
    """
    sym = symbol.upper().strip()
    try:
        from utils.multi_tf_scanner import analyze_symbol  # type: ignore
        res = await analyze_symbol(symbol=sym, interval=interval, market_type=market, bars=bars)
        r = res or {}
        item = AiManualScanItem(
            symbol=sym,
            market=market,
            interval=interval,
            frames=[interval],
            trend=r.get("trend"),
            direction=r.get("direction"),
            rsi=r.get("rsi"),
            adx=r.get("adx"),
            volume=r.get("volume"),
            quality_score=r.get("quality_score"),
            signal=r.get("signal"),
            confidence=r.get("confidence"),
            reason=r.get("reason"),
            close=r.get("close"),
            atr=r.get("atr"),
        )
        return AiManualScanResponse(symbol=sym, results=item)
    except Exception as e:
        # פולבק ניטרלי — לא 500
        item = AiManualScanItem(
            symbol=sym,
            market=market,
            interval=interval,
            frames=[interval],
            trend=None,
            direction=None,
            rsi=None,
            adx=None,
            volume=None,
            quality_score=None,
            signal=None,
            confidence=None,
            reason=f"analyze-fallback: {type(e).__name__}",
            close=None,
            atr=None,
        )
        return AiManualScanResponse(symbol=sym, results=item)



















