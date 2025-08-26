# routes/ai.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, Query, HTTPException
from pydantic import BaseModel, Field
import os

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality import compute_quality
from utils.indicators import prepare_indicators_for_backtest
from utils.get_klines import aget_klines  # async wrapper

try:
    from utils.ai_analysis import analyze_with_ai
except Exception:
    analyze_with_ai = None  # type: ignore

router = APIRouter(tags=["AI"], dependencies=[Depends(require_api_key)])
Side = Literal["LONG", "SHORT"]

# -------------------------
# Models
# -------------------------
class QualityRequest(BaseModel):
    symbol: str
    side: Side
    entry: Optional[float] = Field(None, ge=0)
    sl: Optional[float] = Field(None, ge=0)
    tp: Optional[float] = Field(None, ge=0)
    leverage: int = Field(10, ge=1, le=125)
    budget: float = Field(100.0, gt=0)
    atr: Optional[float] = Field(None, gt=0)

class QualityResponse(BaseModel):
    quality_score: float
    success_pct: float
    anchor: Dict[str, Any]
    components: Dict[str, Any]

class AnalyzeRequest(BaseModel):
    symbol: str = Field(..., description="Trading pair symbol, e.g. BTCUSDT")
    interval: str = Field("15m", description="Kline interval, e.g. 15m,1h,4h")

# -------------------------
# Helpers
# -------------------------
def _mk_anchor_dict(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

def _fallback_text(row: Dict[str, Any], symbol: str, interval: str) -> str:
    ema_bias = "long" if row.get("ema21", 0) > row.get("ema50", 0) else "short"
    rsi = row.get("rsi", 50.0)
    adx = row.get("adx", 15.0)
    return f"[Fallback] {symbol} {interval}: bias={ema_bias}, rsi={rsi:.1f}, adx={adx:.1f}"

# -------------------------
# Routes
# -------------------------
@router.get("/ping")
async def ping():
    return {"ok": True, "model": os.getenv("OPENAI_MODEL", "gpt-4o")}

@router.get("/health")
async def ai_health():
    ok = bool(os.getenv("OPENAI_API_KEY"))
    return {
        "ok": ok,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "reason": None if ok else "Missing OPENAI_API_KEY",
    }

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

# --- ניתוח (GET/POST) ---
@router.get("/analyze")
async def ai_analyze_get(symbol: str = Query(...), interval: str = Query("15m")):
    return await _do_ai_analyze(symbol, interval)

@router.post("/analyze")
async def ai_analyze_post(payload: AnalyzeRequest = Body(...)):
    return await _do_ai_analyze(payload.symbol, payload.interval)

async def _do_ai_analyze(symbol: str, interval: str):
    try:
        df = await aget_klines(symbol, interval, limit=200, market_type="futures")
        if df is None or len(df) == 0:
            raise HTTPException(status_code=502, detail="No klines data returned")
        indicators = prepare_indicators_for_backtest(df)
        if indicators is None or len(indicators) == 0:
            raise HTTPException(status_code=502, detail="Indicators preparation failed")

        last_row = indicators.iloc[-1].to_dict()
        if analyze_with_ai:
            res = await analyze_with_ai({"symbol": symbol.upper(), **last_row})
            return {
                "symbol": symbol.upper(),
                "interval": interval,
                "analysis": res.get("analysis", ""),
                "fallback": not res.get("ok", False),
            }
        else:
            return {
                "symbol": symbol.upper(),
                "interval": interval,
                "analysis": _fallback_text(last_row, symbol.upper(), interval),
                "fallback": True,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI analyze failed: {e}")

@router.get("/manual-scan")
async def ai_manual_scan(symbols: str = Query(...), interval: str = Query("15m")):
    result: List[Dict[str, Any]] = []
    for s in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        try:
            df = await aget_klines(s, interval, limit=200, market_type="futures")
            if df is None or len(df) == 0:
                result.append({"symbol": s, "error": "No klines data returned"})
                continue
            indicators = prepare_indicators_for_backtest(df)
            if indicators is None or len(indicators) == 0:
                result.append({"symbol": s, "error": "Indicators preparation failed"})
                continue
            last = indicators.iloc[-1].to_dict()
            if analyze_with_ai:
                res = await analyze_with_ai({"symbol": s, **last})
                result.append({
                    "symbol": s,
                    "analysis": res.get("analysis", ""),
                    "fallback": not res.get("ok", False),
                })
            else:
                result.append({
                    "symbol": s,
                    "analysis": _fallback_text(last, s, interval),
                    "fallback": True,
                })
        except Exception as e:
            result.append({"symbol": s, "error": str(e)})
    return {"interval": interval, "results": result}


































