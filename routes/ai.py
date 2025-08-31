# routes/ai.py
from __future__ import annotations

import os
import asyncio
from typing import Optional, Literal, Dict, Any, List, Tuple

from fastapi import APIRouter, Depends, Body, Query
from pydantic import BaseModel, Field

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality_score import compute_quality
from utils.ws_fallback import get_price, is_price_fresh
from utils.binance_client import futures_mark_price

router = APIRouter(prefix="/ai", tags=["AI"], dependencies=[Depends(require_api_key)])

Side = Literal["LONG", "SHORT"]

# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _mk_anchor(anchor: AnchorDecision) -> Dict[str, Any]:
    return {
        "mode_requested": getattr(anchor, "mode_requested", None),
        "mode_applied": getattr(anchor, "mode_applied", None),
        "bias": getattr(anchor, "bias", None),
        "score": getattr(anchor, "score", None),
        "severity": getattr(anchor, "severity", None),
        "reason": getattr(anchor, "reason", None),
    }

def _cache_price(symbol: str, max_age_sec: int = 60) -> Tuple[Optional[float], bool]:
    s = symbol.strip().upper()
    px = get_price(s)
    fresh = bool(px) and is_price_fresh(s, max_age_sec=max_age_sec)
    return (float(px) if px else None), fresh

async def _best_price(symbol: str, max_age_sec: int = 60) -> Tuple[Optional[float], bool]:
    s = symbol.strip().upper()
    px, fresh = _cache_price(s, max_age_sec=max_age_sec)
    if fresh and px is not None:
        return px, True
    # fallback ל־mark price מה־REST (ב־thread pool כדי לא לחסום event loop)
    try:
        mp = await asyncio.to_thread(futures_mark_price, s)
        if mp and mp > 0:
            return float(mp), True
    except Exception:
        pass
    return px, False

def _quick_analysis_text(symbol: str, interval: str, reason: str = "") -> str:
    px, fresh = _cache_price(symbol)
    extra = f" (reason: {reason})" if reason else ""
    fresh_tag = "fresh" if fresh else "stale"
    if px is not None:
        return f"[Quick] {symbol.upper()} {interval}: price≈{px} ({fresh_tag}){extra}"
    return f"[Quick] {symbol.upper()} {interval}: price unavailable{extra}"

def _load_klines_and_indicators():
    try:
        from utils.get_klines import aget_klines
        from utils.indicators import prepare_indicators_for_backtest
        return aget_klines, prepare_indicators_for_backtest, None
    except Exception as e:
        return None, None, str(e)

def _load_ai_analysis():
    try:
        from utils.ai_analysis import analyze_with_ai  # אופציונלי
        return analyze_with_ai, None
    except Exception as e:
        return None, str(e)

# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/ping")
async def ping():
    return {"ok": True, "model": os.getenv("OPENAI_MODEL", "gpt-4o")}

@router.get("/health")
async def ai_health():
    ok = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    return {"ok": ok, "model": os.getenv("OPENAI_MODEL", "gpt-4o"), "reason": None if ok else "Missing OPENAI_API_KEY"}

@router.get("/price")
async def ai_price(symbol: str = Query(..., description="e.g. BTCUSDT")):
    s = symbol.strip().upper()
    price, fresh = await _best_price(s)
    return {"symbol": s, "price": price, "fresh": fresh}

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
        anchor=_mk_anchor(anchor),
    )

@router.get("/analyze")
async def ai_analyze_get(symbol: str = Query(...), interval: str = Query("15m")):
    return await _do_ai_analyze(symbol, interval)

@router.post("/analyze")
async def ai_analyze_post(payload: AnalyzeRequest = Body(...)):
    return await _do_ai_analyze(payload.symbol, payload.interval)

async def _do_ai_analyze(symbol: str, interval: str):
    aget_klines, prep, imp_err = _load_klines_and_indicators()
    if imp_err:
        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "analysis": _quick_analysis_text(symbol, interval, f"deps unavailable: {imp_err}"),
            "fallback": True,
        }
    try:
        df = await aget_klines(symbol, interval, limit=200, market_type="futures")
        if df is None or len(df) == 0:
            return {"symbol": symbol.upper(), "interval": interval, "analysis": _quick_analysis_text(symbol, interval, "no klines"), "fallback": True}
        indicators = prep(df)
        if indicators is None or len(indicators) == 0:
            return {"symbol": symbol.upper(), "interval": interval, "analysis": _quick_analysis_text(symbol, interval, "indicators failed"), "fallback": True}
        last = indicators.iloc[-1].to_dict()

        analyze_with_ai, ai_err = _load_ai_analysis()
        if analyze_with_ai and not ai_err:
            try:
                res = await analyze_with_ai({"symbol": symbol.upper(), **last})
                ok = bool(res.get("ok"))
                text = res.get("analysis") or _quick_analysis_text(symbol, interval, "AI returned empty")
                return {"symbol": symbol.upper(), "interval": interval, "analysis": text, "fallback": not ok}
            except Exception as e:
                return {"symbol": symbol.upper(), "interval": interval, "analysis": _quick_analysis_text(symbol, interval, str(e)), "fallback": True}
        else:
            return {"symbol": symbol.upper(), "interval": interval, "analysis": _quick_analysis_text(symbol, interval, ai_err or "AI not available"), "fallback": True}
    except Exception as e:
        return {"symbol": symbol.upper(), "interval": interval, "analysis": _quick_analysis_text(symbol, interval, f"analyze failed: {e}"), "fallback": True}

# סריקה מלאה (מנסה אינדיקטורים; נופל חינני ל־Quick)
@router.get("/manual-scan")
async def ai_manual_scan(symbols: str = Query(...), interval: str = Query("15m")):
    results: List[Dict[str, Any]] = []
    aget_klines, prep, imp_err = _load_klines_and_indicators()
    if imp_err:
        # נפילה חיננית: החזר Quick עבור כל סימבול
        out: List[Dict[str, Any]] = []
        for s in [x.strip().upper() for x in symbols.split(",") if x.strip()]:
            out.append({"symbol": s, "analysis": _quick_analysis_text(s, interval, f"deps unavailable: {imp_err}"), "fallback": True})
        return {"interval": interval, "results": out}

    for s in [x.strip().upper() for x in symbols.split(",") if x.strip()]:
        try:
            df = await aget_klines(s, interval, limit=200, market_type="futures")
            if df is None or len(df) == 0:
                results.append({"symbol": s, "analysis": _quick_analysis_text(s, interval, "no klines"), "fallback": True})
                continue

            indicators = prep(df)
            if indicators is None or len(indicators) == 0:
                results.append({"symbol": s, "analysis": _quick_analysis_text(s, interval, "indicators failed"), "fallback": True})
                continue

            last = indicators.iloc[-1].to_dict()

            analyze_with_ai, ai_err = _load_ai_analysis()
            if analyze_with_ai and not ai_err:
                try:
                    res = await analyze_with_ai({"symbol": s, **last})
                    results.append({"symbol": s, "analysis": res.get("analysis", "") or _quick_analysis_text(s, interval, "AI returned empty"), "fallback": not res.get("ok", False)})
                except Exception as e:
                    results.append({"symbol": s, "analysis": _quick_analysis_text(s, interval, str(e)), "fallback": True})
            else:
                results.append({"symbol": s, "analysis": _quick_analysis_text(s, interval, ai_err or "AI not available"), "fallback": True})
        except Exception as e:
            results.append({"symbol": s, "analysis": _quick_analysis_text(s, interval, f"error: {e}"), "fallback": True})

    return {"interval": interval, "results": results}

# אליאס תאימות לאחור: קל ומהיר (מחזיר 200 תמיד; לא טוען אינדיקטורים)
@router.get("/manual_scan")
async def ai_manual_scan_compat(
    symbol: Optional[str] = Query(None, description="Single symbol (e.g. BTCUSDT)"),
    symbols: Optional[str] = Query(None, description="Comma-separated (e.g. BTCUSDT,ETHUSDT)"),
    interval: str = Query("15m"),
    max_price_age_sec: int = Query(120),
    mode: Optional[str] = Query(None, description="Kept for backward-compat; ignored"),
):
    # איחוד קלט
    syms: List[str] = []
    if symbols and symbols.strip():
        syms.extend([x.strip().upper() for x in symbols.split(",") if x.strip()])
    if symbol and symbol.strip():
        syms.append(symbol.strip().upper())
    syms = [s for s in syms if s]

    if not syms:
        return {"interval": interval, "results": [{"error": "No symbols provided"}]}

    out: List[Dict[str, Any]] = []
    for s in syms:
        px, fresh = await _best_price(s, max_age_sec=max_price_age_sec)
        analysis = f"[Quick] {s} {interval}: " + (f"price≈{px} ({'fresh' if fresh else 'stale'})" if px is not None else "price unavailable")
        out.append({"symbol": s, "price": px, "fresh": fresh, "analysis": analysis, "fallback": True})

    return {"interval": interval, "results": out}















































