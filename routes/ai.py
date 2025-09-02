# routes/ai.py
from __future__ import annotations

import os
import asyncio
from typing import Optional, Literal, Dict, Any, List

from fastapi import APIRouter, Depends, Body, Query, HTTPException
from pydantic import BaseModel, Field
import httpx

from utils.auth import require_api_key
from utils.anchor import evaluate_anchor, AnchorDecision
from utils.quality_score import compute_quality
from utils.ws_fallback import get_price, is_price_fresh
from utils.binance_client import futures_mark_price

# Early approvals / filter
from utils.ai_analysis import analyze_with_ai, analyze_with_ai_and_filter
from utils.approvals import preflight_proposal

router = APIRouter(prefix="/ai", tags=["AI"], dependencies=[Depends(require_api_key)])

Side = Literal["LONG", "SHORT"]

# =======================
# Models
# =======================
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

class SuggestRequest(BaseModel):
    symbols: List[str] = Field(default_factory=list)
    interval: str = Field(default_factory=lambda: os.getenv("DEFAULT_INTERVAL", "15m"))
    market: str = Field(default_factory=lambda: os.getenv("DEFAULT_MARKET", "futures"))
    max_items: int = Field(10, ge=1, le=50)
    include_rejected: bool = True

class QueueMode(str):
    TELEGRAM = "telegram"
    SINK = "sink"

class SuggestQueueRequest(BaseModel):
    symbols: List[str] = Field(default_factory=list)
    interval: str = Field(default_factory=lambda: os.getenv("DEFAULT_INTERVAL", "15m"))
    market: str = Field(default_factory=lambda: os.getenv("DEFAULT_MARKET", "futures"))
    max_items: int = Field(10, ge=1, le=50)
    mode: Literal["telegram","sink"] = Field(default="telegram")
    # override env flags:
    queue_to_telegram: Optional[bool] = None
    auto_execute_sink: Optional[bool] = None

# =======================
# Helpers
# =======================
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

async def _best_price(symbol: str) -> tuple[Optional[float], bool]:
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
    if px:
        return f"[Quick] {symbol.upper()} {interval}: price≈{px}{extra}"
    return f"[Quick] {symbol.upper()} {interval}: price unavailable{extra}"

def _load_klines_and_indicators():
    try:
        from utils.get_klines import aget_klines
        from utils.indicators import prepare_indicators_for_backtest
        return aget_klines, prepare_indicators_for_backtest, None
    except Exception as e:
        return None, None, str(e)

def _bearer() -> str:
    return f"Bearer {os.getenv('API_BEARER_TOKEN','').strip()}"

TELEGRAM_ADD_PENDING_URL = "/telegram/pending/add"
ALERTS_INGEST_URL = os.getenv("ALERTS_INGEST_URL", "http://127.0.0.1:8000/alerts/trade-ingest").strip()

# =======================
# Endpoints
# =======================
@router.get("/ping")
async def ping():
    return {"ok": True, "model": os.getenv("OPENAI_MODEL", "gpt-4o")}

@router.get("/health")
async def ai_health():
    ok = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    return {"ok": ok, "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "reason": None if ok else "Missing OPENAI_API_KEY"}

@router.get("/price")
async def ai_price(symbol: str = Query(..., description="e.g. BTCUSDT")):
    s = symbol.strip().upper()
    price, fresh = await _best_price(s)
    return {"symbol": s, "price": price, "fresh": fresh}

@router.post("/quality", response_model=QualityResponse)
async def ai_quality(payload: QualityRequest = Body(...)):
    anchor = evaluate_anchor(payload.side)
    q = compute_quality(
        symbol=payload.symbol, side=payload.side,
        entry=payload.entry, sl=payload.sl, tp=payload.tp,
        leverage=payload.leverage, budget=payload.budget,
        anchor=anchor, atr=payload.atr,
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
        return {"symbol": symbol.upper(), "interval": interval,
                "analysis": _quick_analysis_text(symbol, interval, imp_err),
                "fallback": True}
    try:
        df = await aget_klines(symbol, interval, limit=200, market_type="futures")
        if df is None or len(df) == 0:
            return {"symbol": symbol.upper(), "interval": interval,
                    "analysis": _quick_analysis_text(symbol, interval, "no klines"),
                    "fallback": True}
        indicators = prep(df)
        if indicators is None or len(indicators) == 0:
            return {"symbol": symbol.upper(), "interval": interval,
                    "analysis": _quick_analysis_text(symbol, interval, "indicators failed"),
                    "fallback": True}
        last = indicators.iloc[-1].to_dict()

        # OpenAI (טקסט) – לא מסנן טריידים; זו אנליזה בלבד
        res = await analyze_with_ai({"symbol": symbol.upper(), **last})
        ok = bool(res.get("ok"))
        text = res.get("analysis") or _quick_analysis_text(symbol, interval, "AI returned empty")
        return {"symbol": symbol.upper(), "interval": interval, "analysis": text, "fallback": not ok}
    except Exception as e:
        return {"symbol": symbol.upper(), "interval": interval,
                "analysis": _quick_analysis_text(symbol, interval, f"analyze failed: {e}"),
                "fallback": True}

# ---- SUGGEST (Candidates + Early Approvals) ----
@router.post("/suggest")
async def suggest(req: SuggestRequest):
    run_early = str(os.getenv("APPROVAL_EARLY_AI","1")).lower() in ("1","true","yes","on")
    res = await analyze_with_ai_and_filter(
        symbols=[s.upper() for s in req.symbols],
        interval=req.interval, market=req.market,
        max_items=req.max_items, run_early_approvals=run_early,
    )
    out = {"ok": True, "interval": req.interval, "market": req.market, "accepted": res["accepted"]}
    if req.include_rejected:
        out["rejected"] = res["rejected"]
    return out

# ---- SUGGEST & QUEUE (to Telegram PENDING or to sink) ----
@router.post("/suggest_and_queue")
async def suggest_and_queue(req: SuggestQueueRequest):
    # הפקה
    run_early = str(os.getenv("APPROVAL_EARLY_AI","1")).lower() in ("1","true","yes","on")
    res = await analyze_with_ai_and_filter(
        symbols=[s.upper() for s in req.symbols],
        interval=req.interval, market=req.market,
        max_items=req.max_items, run_early_approvals=run_early,
    )
    accepted = res["accepted"]

    if not accepted:
        return {"ok": True, "queued": 0, "mode": req.mode, "accepted": []}

    # קונפיג יעד
    env_to_tg = str(os.getenv("AI_QUEUE_TO_TELEGRAM","1")).lower() in ("1","true","yes","on")
    env_auto  = str(os.getenv("AI_QUEUE_AUTO_EXECUTE","0")).lower() in ("1","true","yes","on")
    to_telegram = req.queue_to_telegram if req.queue_to_telegram is not None else env_to_tg
    auto_exec   = req.auto_execute_sink if req.auto_execute_sink is not None else env_auto

    # דחיפה
    queued: List[Dict[str, Any]] = []
    headers = {"Authorization": _bearer(), "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for c in accepted:
            payload = {**c}
            if to_telegram and req.mode == "telegram":
                # דחיפה ל-PENDING של הטלגרם + שליחת הודעה עם כפתורים
                url = TELEGRAM_ADD_PENDING_URL  # local path; נשתמש ב-root באותו שרת
                try:
                    r = await client.post(url, json={"tp": payload, "interval": req.interval, "market": req.market}, headers=headers)
                    r.raise_for_status()
                    queued.append({"symbol": c["symbol"], "side": c["side"], "target": "telegram"})
                except Exception as e:
                    queued.append({"symbol": c["symbol"], "side": c["side"], "target": "telegram", "error": str(e)})
            if auto_exec or req.mode == "sink":
                # שילוח ישיר ל-sink (אוטו-ביצוע/פרסום)
                try:
                    # preflight (קשיח): אם נופל – לא שולחים
                    pf = preflight_proposal({**payload, "interval": req.interval})
                    if not pf.get("ok", False):
                        queued.append({"symbol": c["symbol"], "side": c["side"], "target": "sink", "error": "preflight_failed", "errors": pf.get("errors",[])})
                        continue
                    rr_body = {  # sink payload אחיד
                        "trade_id": None,  # יתמלא ב-sink
                        "trade_type": "FUTURES" if req.market.lower().startswith("future") else "SPOT",
                        "symbol": c["symbol"], "side": c["side"],
                        "current_price": c.get("current_price"),
                        "entry": c["entry"], "sl": c["sl"],
                        "tp1": c["tp1"], "tp2": c.get("tp2"), "tp3": c.get("tp3"),
                        "leverage": c.get("leverage", 10),
                        "success_pct": c.get("success_pct"),
                        "reason": "auto-exec via /ai/suggest_and_queue",
                        "interval": req.interval, "market": req.market,
                    }
                    r = await client.post(ALERTS_INGEST_URL, json=rr_body, headers={"Accept":"application/json"})
                    r.raise_for_status()
                    queued.append({"symbol": c["symbol"], "side": c["side"], "target": "sink"})
                except Exception as e:
                    queued.append({"symbol": c["symbol"], "side": c["side"], "target": "sink", "error": str(e)})

    return {"ok": True, "mode": req.mode, "queued": len([q for q in queued if "error" not in q]), "details": queued}


















































