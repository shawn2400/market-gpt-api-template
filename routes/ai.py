# routes/ai.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, Query, HTTPException
from pydantic import BaseModel, Field
from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality import compute_quality
from utils.indicators import prepare_indicators_for_backtest
from utils.get_klines import get_klines  # async

# analyze_with_ai עלול לא להיות זמין/לזרוק שגיאה בכלי
try:
    from utils.ai_analysis import analyze_with_ai
except Exception:
    analyze_with_ai = None  # type: ignore

router = APIRouter(tags=["AI"], dependencies=[Depends(require_api_key)])

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

@router.get("/ping")
async def ping():
    import os
    return {"ok": True, "model": os.getenv("OPENAI_MODEL", "gpt-4o")}

@router.get("/health")
async def ai_health():
    import os
    ok = bool(os.getenv("OPENAI_API_KEY"))
    return {"ok": ok, "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "reason": None if ok else "Missing OPENAI_API_KEY"}

@router.post("/quality", response_model=QualityResponse)
async def ai_quality(payload: QualityRequest = Body(...)):
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

def _fallback_text(last_row: Dict[str, Any], symbol: str, interval: str) -> str:
    ema_bias = "long" if last_row.get("ema21", 0) > last_row.get("ema50", 0) else "short"
    rsi = last_row.get("rsi", 50.0)
    adx = last_row.get("adx", 15.0)
    return (f"[Fallback] {symbol} {interval}: bias={ema_bias}, rsi={rsi:.1f}, adx={adx:.1f}. "
            f"Use ATR for SL/TP; wait for confluence on dual TF.")

@router.get("/analyze")
async def ai_analyze(symbol: str = Query(...), interval: str = Query("15m")):
    try:
        # ❗ ללא market=...
        df = await get_klines(symbol, interval, limit=200)
        if df is None or len(df) == 0:
            raise HTTPException(status_code=502, detail="No klines data returned")

        indicators = prepare_indicators_for_backtest(df)
        if indicators is None or len(indicators) == 0:
            raise HTTPException(status_code=502, detail="Indicators preparation failed")

        last_row = indicators.iloc[-1].to_dict()
        if analyze_with_ai:
            try:
                txt = await analyze_with_ai({"symbol": symbol.upper(), **last_row})
                return {"symbol": symbol.upper(), "interval": interval, "analysis": txt, "fallback": False}
            except Exception as e:
                return {
                    "symbol": symbol.upper(), "interval": interval,
                    "analysis": _fallback_text(last_row, symbol.upper(), interval),
                    "fallback": True, "error": str(e)
                }
        else:
            return {
                "symbol": symbol.upper(), "interval": interval,
                "analysis": _fallback_text(last_row, symbol.upper(), interval),
                "fallback": True
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI analyze failed: {str(e)}")

@router.get("/manual-scan")
async def ai_manual_scan(symbols: str = Query(...), interval: str = Query("15m")):
    result = []
    for s in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        try:
            df = await get_klines(s, interval, limit=200)  # ❗ ללא market=...
            if df is None or len(df) == 0:
                result.append({"symbol": s, "error": "No klines data returned"})
                continue

            indicators = prepare_indicators_for_backtest(df)
            if indicators is None or len(indicators) == 0:
                result.append({"symbol": s, "error": "Indicators preparation failed"})
                continue

            last_row = indicators.iloc[-1].to_dict()
            if analyze_with_ai:
                try:
                    txt = await analyze_with_ai({"symbol": s, **last_row})
                    result.append({"symbol": s, "analysis": txt, "fallback": False})
                except Exception as e:
                    result.append({"symbol": s, "analysis": _fallback_text(last_row, s, interval),
                                   "fallback": True, "error": str(e)})
            else:
                result.append({"symbol": s, "analysis": _fallback_text(last_row, s, interval),
                               "fallback": True})
        except Exception as e:
            result.append({"symbol": s, "error": str(e)})
    return {"interval": interval, "results": result}



























