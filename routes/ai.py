# routes/ai.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, Query, HTTPException
from pydantic import BaseModel, Field
import pandas as pd
from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality import compute_quality
from utils.ai_analysis import analyze_with_ai
from utils.indicators import prepare_indicators_for_backtest
from utils.get_klines import get_klines  # שימוש בנתונים חיים מ-Binance

router = APIRouter(
    prefix="/ai",
    tags=["AI"],
    dependencies=[Depends(require_api_key)],
)

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
    """
    בדיקה אם מפתח OpenAI נטען.
    """
    import os
    ok = bool(os.getenv("OPENAI_API_KEY"))
    return {
        "ok": ok,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "reason": None if ok else "Missing OPENAI_API_KEY",
    }

@router.post("/quality", response_model=QualityResponse)
async def ai_quality(payload: QualityRequest = Body(...)):
    """
    חישוב ציון איכות לטרייד.
    """
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

@router.get("/analyze")
async def ai_analyze(symbol: str = Query(...), interval: str = Query("15m")):
    """
    ניתוח GPT בסיסי עם אינדיקטורים.
    """
    try:
        df = await get_klines(symbol, interval, limit=200, market="futures")
        indicators = prepare_indicators_for_backtest(df)
        last_row = indicators.iloc[-1].to_dict()
        txt = await analyze_with_ai({"symbol": symbol.upper(), **last_row})
        return {"symbol": symbol.upper(), "interval": interval, "analysis": txt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI analyze failed: {str(e)}")

@router.get("/manual-scan")
async def ai_manual_scan(symbols: str = Query(...), interval: str = Query("15m")):
    """
    סריקה ידנית של כמה סימבולים עם ניתוח GPT על סמך אינדיקטורים חיים.
    """
    result = []
    for s in [s.strip().upper() for s in symbols.split(",")]:
        try:
            df = await get_klines(s, interval, limit=200, market="futures")
            indicators = prepare_indicators_for_backtest(df)
            last_row = indicators.iloc[-1].to_dict()
            txt = await analyze_with_ai({"symbol": s, **last_row})
            result.append({"symbol": s, "analysis": txt})
        except Exception as e:
            result.append({"symbol": s, "error": str(e)})
    return {"interval": interval, "results": result}

























