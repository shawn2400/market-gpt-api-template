from __future__ import annotations
from typing import Optional, Literal, Dict, Any, List
from fastapi import APIRouter, Depends, Body, Query, HTTPException
from pydantic import BaseModel, Field
import os

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality import compute_quality
from utils.ws_fallback import get_price, is_price_fresh

router = APIRouter(
    prefix="/ai",
    tags=["AI"],
    dependencies=[Depends(require_api_key)],
)

Side = Literal["LONG", "SHORT"]

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

def _mk_anchor_dict(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

def _fallback_text(row: Dict[str, Any], symbol: str, interval: str, reason: str = "") -> str:
    ema_bias = "long" if row.get("ema_21", 0) > row.get("ema_50", 0) else "short"
    rsi = row.get("rsi", 50.0)
    adx = row.get("adx", 15.0)
    extra = f" ({reason})" if reason else ""
    px = get_price(symbol.upper()); fresh = is_price_fresh(symbol.upper(), max_age_sec=10)
    price_note = f", mark={px}" if px and fresh else ""
    return f"[Fallback] {symbol.upper()} {interval}: bias={ema_bias}, rsi={rsi:.1f}, adx={adx:.1f}{price_note}{extra}"

def _load_klines_and_indicators():
    try:
        from utils.get_klines import aget_klines
        from utils.indicators import prepare_indicators_for_backtest
        return aget_klines, prepare_indicators_for_backtest, None
    except Exception as e:
        return None, None, str(e)

def _load_ai_analysis():
    try:
        from utils.ai_analysis import analyze_with_ai
        return analyze_with_ai, None
    except Exception as e:
        return None, str(e)

@router.get("/ping")
async def ping():
    return {"ok": True, "model": os.getenv("OPENAI_MODEL", "gpt-4o")}

@router.get("/health")
async def ai_health():
    ok = bool(os.getenv("OPENAI_API_KEY"))
    return {"ok": ok, "model": os.getenv("OPENAI_MODEL", "gpt-4o"), "reason": None if ok else "Missing OPENAI_API_KEY"}

@router.get("/price")
async def ai_price(symbol: str = Query(..., description="e.g. BTCUSDT")):
    s = symbol.strip().upper()
    px = get_price(s)
    return {"symbol": s, "price": px, "fresh": is_price_fresh(s, max_age_sec=10)}

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

@router.get("/analyze")
async def ai_analyze_get(symbol: str = Query(...), interval: str = Query("15m")):
    return await _do_ai_analyze(symbol, interval)

@router.post("/analyze")
async def ai_analyze_post(payload: AnalyzeRequest = Body(...)):
    return await _do_ai_analyze(payload.symbol, payload.interval)

async def _do_ai_analyze(symbol: str, interval: str):
    aget_klines, prepare_indicators_for_backtest, imp_err = _load_klines_and_indicators()
    if imp_err:
        return {"symbol": symbol.upper(), "interval": interval, "analysis": f"[Fallback] dependencies unavailable: {imp_err}", "fallback": True}
    try:
        df = await aget_klines(symbol, interval, limit=200, market_type="futures")
        if df is None or len(df) == 0:
            return {"symbol": symbol.upper(), "interval": interval, "analysis": "[Fallback] no klines data returned", "fallback": True}
        indicators = prepare_indicators_for_backtest(df)
        if indicators is None or len(indicators) == 0:
            return {"symbol": symbol.upper(), "interval": interval, "analysis": "[Fallback] indicators preparation failed", "fallback": True}
        last_row = indicators.iloc[-1].to_dict()
        analyze_with_ai, ai_err = _load_ai_analysis()
        if analyze_with_ai and not ai_err:
            try:
                res = await analyze_with_ai({"symbol": symbol.upper(), **last_row})
                return {"symbol": symbol.upper(), "interval": interval, "analysis": res.get("analysis", ""), "fallback": not res.get("ok", False)}
            except Exception as e:
                return {"symbol": symbol.upper(), "interval": interval, "analysis": _fallback_text(last_row, symbol.upper(), interval, str(e)), "fallback": True}
        else:
            return {"symbol": symbol.upper(), "interval": interval, "analysis": _fallback_text(last_row, symbol.upper(), interval, ai_err or "AI not available"), "fallback": True}
    except Exception as e:
        return {"symbol": symbol.upper(), "interval": interval, "analysis": f"[Fallback] AI analyze failed: {e}", "fallback": True}

@router.get("/manual-scan")
async def ai_manual_scan(symbols: str = Query(...), interval: str = Query("15m")):
    result: List[Dict[str, Any]] = []
    aget_klines, prepare_indicators_for_backtest, imp_err = _load_klines_and_indicators()
    if imp_err:
        return {"interval": interval, "results": [{"error": f"dependencies unavailable: {imp_err}"}]}
    for s in [s.strip().upper() for s in symbols.split(",") if s.strip()]:
        try:
            df = await aget_klines(s, interval, limit=200, market_type="futures")
            if df is None or len(df) == 0:
                result.append({"symbol": s, "error": "No klines data returned"}); continue
            indicators = prepare_indicators_for_backtest(df)
            if indicators is None or len(indicators) == 0:
                result.append({"symbol": s, "error": "Indicators preparation failed"}); continue
            last = indicators.iloc[-1].to_dict()
            analyze_with_ai, ai_err = _load_ai_analysis()
            if analyze_with_ai and not ai_err:
                try:
                    res = await analyze_with_ai({"symbol": s, **last})
                    result.append({"symbol": s, "analysis": res.get("analysis", ""), "fallback": not res.get("ok", False)})
                except Exception as e:
                    result.append({"symbol": s, "analysis": _fallback_text(last, s, interval, str(e)), "fallback": True})
            else:
                result.append({"symbol": s, "analysis": _fallback_text(last, s, interval, ai_err or "AI not available"), "fallback": True})
        except Exception as e:
            result.append({"symbol": s, "error": str(e)})
    return {"interval": interval, "results": result}







































