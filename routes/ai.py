from __future__ import annotations
from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, HTTPException, Query, Header
from pydantic import BaseModel, Field

# --- Auth ---
try:
    from utils.auth import require_bearer_token as _raw_require_bearer  # type: ignore
    def require_bearer_token(
        authorization: Optional[str] = Header(default=None, convert_underscores=False),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-KEY"),
        token: Optional[str] = Query(default=None),
    ):
        if x_api_key:
            return _raw_require_bearer(authorization=f"Bearer {x_api_key}")
        if authorization:
            return _raw_require_bearer(authorization=authorization)
        if token:
            return _raw_require_bearer(authorization=f"Bearer {token}")
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

router = APIRouter(tags=["AI"])
Side = Literal["LONG", "SHORT"]

# =========================
# Models
# =========================
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

class AiManualScanItem(BaseModel):
    symbol: str
    market: Optional[str] = None
    interval: Optional[str] = None
    frames: List[str] = Field(default_factory=list)
    trend: Optional[Literal["UP", "DOWN"]] = None
    direction: Optional[Side] = None
    rsi: Optional[float] = None
    adx: Optional[float] = None
    volume: Optional[float] = None
    quality_score: Optional[float] = None
    signal: Optional[Literal["BUY", "SELL", "HOLD"]] = None
    confidence: Optional[int] = None
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

# =========================
# Endpoints
# =========================
@router.get("/health", summary="AI Health")
async def ai_health():
    import os
    ok = bool(os.getenv("OPENAI_API_KEY"))
    return {
        "ok": ok,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "reason": None if ok else "Missing OPENAI_API_KEY"
    }

@router.post("/quality", response_model=QualityResponse)
async def post_ai_quality(
    payload: QualityRequest = Body(...),
    _auth=Depends(require_bearer_token),
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

@router.get("/manual-scan", response_model=AiManualScanResponse)
async def get_ai_manual_scan(
    symbol: str = Query(...),
    market: str = Query("futures"),
    interval: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    _auth=Depends(require_bearer_token),
) -> AiManualScanResponse:
    sym = symbol.upper().strip()
    try:
        from utils.multi_tf_scanner import analyze_symbol
        res = await analyze_symbol(symbol=sym, interval=interval, market_type=market, bars=bars)
        return AiManualScanResponse(symbol=sym, results=AiManualScanItem(**res))
    except Exception as e:
        return AiManualScanResponse(
            symbol=sym,
            results=AiManualScanItem(symbol=sym, market=market, interval=interval, reason=f"analyze-fallback: {type(e).__name__}")
        )






















