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

# ──────────────────────────────────────────────────────────────────────────────
# Models / Types
# ──────────────────────────────────────────────────────────────────────────────

Side = Literal["LONG", "SHORT"]


class HealthResponse(BaseModel):
    ok: bool
    model: str
    reason: Optional[str] = None


class PriceResponse(BaseModel):
    symbol: str
    price: Optional[float]
    fresh: bool


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


class AnalyzeResponse(BaseModel):
    symbol: str
    interval: str
    analysis: str
    fallback: bool


class ManualScanResult(BaseModel):
    symbol: str
    analysis: Optional[str] = None
    fallback: Optional[bool] = None
    error: Optional[str] = None


class ManualScanFullResponse(BaseModel):
    interval: str
    results: List[ManualScanResult]


class ManualScanLegacyResponse(BaseModel):
    symbol: str
    interval: str
    fresh: bool
    analysis: str
    fallback: bool = True
    price: Optional[float] = None


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


def _cache_price(symbol: str) -> Optional[float]:
    s = symbol.strip().upper()
    px = get_price(s)
    if px and is_price_fresh(s, max_age_sec=60):
        return float(px)
    return None


async def _best_price(symbol: str) -> Tuple[Optional[float], bool]:
    """
    Returns (price, fresh). Try WS cache first; if stale, fall back to REST mark price.
    """
    s = symbol.strip().upper()
    px = get_price(s)
    fresh = bool(px) and is_price_fresh(s, max_age_sec=60)
    if fresh:
        return float(px), True
    try:
        mp = await asyncio.to_thread(futures_mark_price, s)
        if mp and mp > 0:
            return float(mp), True
    except Exception:
        pass
    return (float(px) if px else None), False


def _quick_analysis_text(symbol: str, interval: str, reason: str = "") -> str:
    px = _cache_price(symbol)
    extra = f" (reason: {reason})" if reason else ""
    if px is not None:
        return f"[Quick] {symbol.upper()} {interval}: price≈{px}{extra}"
    return f"[Quick] {symbol.upper()} {interval}: price unavailable{extra}"


def _load_klines_and_indicators():
    """Try to import klines & indicators. If not available, return error string (for graceful fallback)."""
    try:
        from utils.get_klines import aget_klines
        from utils.indicators import prepare_indicators_for_backtest
        return aget_klines, prepare_indicators_for_backtest, None
    except Exception as e:
        return None, None, str(e)


def _load_ai_analysis():
    """Optional AI hook (utils.ai_analysis.analyze_with_ai)."""
    try:
        from utils.ai_analysis import analyze_with_ai  # async function expected
        return analyze_with_ai, None
    except Exception as e:
        return None, str(e)


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/ping")
async def ping():
    return {"ok": True, "model": os.getenv("OPENAI_MODEL", "gpt-4o")}


@router.get("/health", response_model=HealthResponse)
async def ai_health():
    ok = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    return HealthResponse(ok=ok, model=os.getenv("OPENAI_MODEL", "gpt-4o"), reason=None if ok else "Missing OPENAI_API_KEY")


@router.get("/price", response_model=PriceResponse)
async def ai_price(symbol: str = Query(..., description="e.g. BTCUSDT")):
    s = symbol.strip().upper()
    price, fresh = await _best_price(s)
    return PriceResponse(symbol=s, price=price, fresh=fresh)


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


@router.get("/analyze", response_model=AnalyzeResponse)
async def ai_analyze_get(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    interval: str = Query("15m", description="Kline interval"),
):
    return await _do_ai_analyze(symbol, interval)


@router.post("/analyze", response_model=AnalyzeResponse)
async def ai_analyze_post(payload: AnalyzeRequest = Body(...)):
    return await _do_ai_analyze(payload.symbol, payload.interval)


async def _do_ai_analyze(symbol: str, interval: str) -> AnalyzeResponse:
    aget_klines, prep, imp_err = _load_klines_and_indicators()
    if imp_err:
        return AnalyzeResponse(
            symbol=symbol.upper(),
            interval=interval,
            analysis=_quick_analysis_text(symbol, interval, imp_err),
            fallback=True,
        )
    try:
        df = await aget_klines(symbol, interval, limit=200, market_type="futures")
        if df is None or len(df) == 0:
            return AnalyzeResponse(
                symbol=symbol.upper(), interval=interval,
                analysis=_quick_analysis_text(symbol, interval, "no klines"),
                fallback=True,
            )

        indicators = prep(df)
        if indicators is None or len(indicators) == 0:
            return AnalyzeResponse(
                symbol=symbol.upper(), interval=interval,
                analysis=_quick_analysis_text(symbol, interval, "indicators failed"),
                fallback=True,
            )

        last = indicators.iloc[-1].to_dict()

        analyze_with_ai, ai_err = _load_ai_analysis()
        if analyze_with_ai and not ai_err:
            try:
                res = await analyze_with_ai({"symbol": symbol.upper(), **last})
                ok = bool(res.get("ok"))
                text = res.get("analysis") or _quick_analysis_text(symbol, interval, "AI returned empty")
                return AnalyzeResponse(symbol=symbol.upper(), interval=interval, analysis=text, fallback=not ok)
            except Exception as e:
                return AnalyzeResponse(
                    symbol=symbol.upper(), interval=interval,
                    analysis=_quick_analysis_text(symbol, interval, str(e)),
                    fallback=True,
                )
        else:
            return AnalyzeResponse(
                symbol=symbol.upper(), interval=interval,
                analysis=_quick_analysis_text(symbol, interval, ai_err or "AI not available"),
                fallback=True,
            )
    except Exception as e:
        return AnalyzeResponse(
            symbol=symbol.upper(), interval=interval,
            analysis=_quick_analysis_text(symbol, interval, f"analyze failed: {e}"),
            fallback=True,
        )


@router.get(
    "/manual-scan",
    response_model=ManualScanFullResponse,
    summary="Full manual scan (multi-symbol) with graceful AI/indicators fallback",
)
async def ai_manual_scan(
    symbols: str = Query(..., description="Comma-separated list, e.g. BTCUSDT,ETHUSDT"),
    interval: str = Query("15m", description="Kline interval"),
):
    """
    מסלול “מלא” — מנסה אינדיקטורים ו־AI אם זמינים, ותמיד מחזיר 200 עם תוצאה פר־סימבול.
    אם התלויות לא זמינות, נחזור ל־quick text לכל סימבול.
    """
    results: List[ManualScanResult] = []
    aget_klines, prep, imp_err = _load_klines_and_indicators()
    if imp_err:
        return ManualScanFullResponse(interval=interval, results=[ManualScanResult(symbol="*", error=f"dependencies unavailable: {imp_err}")])

    for s in [x.strip().upper() for x in symbols.split(",") if x.strip()]:
        try:
            df = await aget_klines(s, interval, limit=200, market_type="futures")
            if df is None or len(df) == 0:
                results.append(ManualScanResult(symbol=s, error="No klines data returned"))
                continue

            indicators = prep(df)
            if indicators is None or len(indicators) == 0:
                results.append(ManualScanResult(symbol=s, error="Indicators preparation failed"))
                continue

            last = indicators.iloc[-1].to_dict()

            analyze_with_ai, ai_err = _load_ai_analysis()
            if analyze_with_ai and not ai_err:
                try:
                    res = await analyze_with_ai({"symbol": s, **last})
                    results.append(ManualScanResult(symbol=s, analysis=res.get("analysis", ""), fallback=not res.get("ok", False)))
                except Exception as e:
                    results.append(ManualScanResult(symbol=s, analysis=_quick_analysis_text(s, interval, str(e)), fallback=True))
            else:
                results.append(ManualScanResult(symbol=s, analysis=_quick_analysis_text(s, interval, ai_err or "AI not available"), fallback=True))
        except Exception as e:
            results.append(ManualScanResult(symbol=s, error=str(e)))

    return ManualScanFullResponse(interval=interval, results=results)


# ──────────────────────────────────────────────────────────────────────────────
# Backward-compat alias: /ai/manual_scan  (quick fallback only)
# ──────────────────────────────────────────────────────────────────────────────

@router.get(
    "/manual_scan",
    response_model=ManualScanLegacyResponse,
    summary="Alias (legacy) — quick fallback scan for a single symbol",
    description=(
        "תאימות לאחור ללקוחות ישנים: מחזיר ניתוח מהיר בלבד (מחיר + fresh) "
        "ואינו מפעיל את תהליך האנליזה המלא."
    ),
)
async def ai_manual_scan_compat(
    symbol: str = Query(..., description="למשל BTCUSDT"),
    interval: str = Query("15m", description="כמו ב-/ai/manual-scan"),
    mode: str = Query("static", description="נשמר לפרוטוקול; לא בשימוש בפועל"),
    max_price_age_sec: int = Query(120, ge=1, le=3600, description="נשמר לפרוטוקול; לא בשימוש בפועל"),
):
    s = symbol.strip().upper()
    price, fresh = await _best_price(s)
    text = f"[Quick] {s} {interval}: price≈{price if price is not None else '?'} (fresh={fresh}) mode={mode}; max_age={max_price_age_sec}s"
    return ManualScanLegacyResponse(symbol=s, interval=interval, fresh=fresh, analysis=text, price=price)













































