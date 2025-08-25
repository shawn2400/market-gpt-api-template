# routes/ai.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, Query
from pydantic import BaseModel, Field
import os

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality import compute_quality
from utils.ai_analysis import analyze_with_ai

# ❌ בלי prefix="/ai" כאן – הוא יתווסף ב-main.py
router = APIRouter(
    tags=["AI"],
    dependencies=[Depends(require_api_key)],  # ✅ כל הנתיבים מחייבים Bearer
)

Side = Literal["LONG", "SHORT"]

# -------- Models --------
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

class AnalysisResult(BaseModel):
    symbol: str
    interval: str
    analysis: str

class ManualScanResponse(BaseModel):
    interval: str
    results: List[Dict[str, Any]]

# -------- Utils --------
def _mk_anchor_dict(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

# -------- Routes --------
@router.get("/health")
async def ai_health():
    ok = bool(os.getenv("OPENAI_API_KEY"))
    return {
        "ok": ok,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "reason": None if ok else "Missing OPENAI_API_KEY",
    }

@router.post("/quality", response_model=QualityResponse)
async def post_ai_quality(payload: QualityRequest = Body(...)) -> QualityResponse:
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

@router.get("/analyze", response_model=AnalysisResult)
async def ai_analyze(symbol: str = Query(...), interval: str = Query("15m")):
    data = {
        "symbol": symbol,
        "rsi": 55,
        "adx": 22,
        "trend": "UP",
        "pattern": "Breakout",
        "volume": "High",
    }
    txt = await analyze_with_ai(data)
    return AnalysisResult(symbol=symbol, interval=interval, analysis=txt)

@router.get("/manual-scan", response_model=ManualScanResponse)
async def ai_manual_scan(symbols: str = Query(...), interval: str = Query("15m")):
    result = []
    for s in symbols.split(","):
        data = {
            "symbol": s.strip(),
            "rsi": 48,
            "adx": 19,
            "trend": "DOWN",
            "pattern": "Pullback",
            "volume": "Medium",
        }
        txt = await analyze_with_ai(data)
        result.append({"symbol": s.strip(), "analysis": txt})
    return ManualScanResponse(interval=interval, results=result)























