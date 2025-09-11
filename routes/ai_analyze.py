# routes/ai_analyze.py
from __future__ import annotations
import os
import time
import logging
from typing import Optional, Dict
from collections import deque

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

try:
    # מדידות (תאימות גם ל-lat וגם ל-latency)
    from utils.metrics_middleware import metrics_exporter  # אם המידלוור טוען אובייקט גלובלי
except Exception:
    metrics_exporter = None

try:
    from utils import metrics_exporter as me  # גיבוי ישיר למודול
except Exception:
    me = None

logger = logging.getLogger("algogpt.ai_analyze")

router = APIRouter(prefix="/ai", tags=["ai"])

# ────────────────────────────────────────────────────────────────────────────────
# קונפיג
# ────────────────────────────────────────────────────────────────────────────────
AI_ANALYZE_ENABLE = os.getenv("AI_ANALYZE_ENABLE", "1").lower() in ("1", "true", "yes", "on")
RL_WINDOW_SEC = int(os.getenv("AI_ANALYZE_WINDOW_SEC", "60"))   # חלון זמן לרייט לימיט
RL_LIMIT = int(os.getenv("AI_ANALYZE_LIMIT", "60"))             # בקשות / חלון
MAX_TEXT_CHARS = int(os.getenv("AI_ANALYZE_MAX_TEXT", "5000"))  # חיתוך טקסט מקסימלי לניתוח

# Rate limit cache (in-memory)
_rl_cache: Dict[str, deque] = {}

# ────────────────────────────────────────────────────────────────────────────────
# מודלים
# ────────────────────────────────────────────────────────────────────────────────
class AnalyzeIn(BaseModel):
    text: str = Field(..., description="טקסט/תיאור לניתוח")
    symbol: Optional[str] = Field(None, description="סימבול רלוונטי (אופציונלי)")
    context: Optional[dict] = Field(None, description="קונטקסט נוסף")
    temperature: Optional[float] = Field(0.2, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(512, ge=16, le=8192)

class AnalyzeOut(BaseModel):
    ok: bool
    ts_ms: int
    symbol: Optional[str] = None
    sentiment: str
    confidence: float
    score: float
    notes: Optional[str] = None

# ────────────────────────────────────────────────────────────────────────────────
# עזר
# ────────────────────────────────────────────────────────────────────────────────
def _client_key(request: Request) -> str:
    # נסה קודם X-Forwarded-For / X-Real-IP (עובד מאחורי פרוקסי), אחרת client.host
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return f"ip:{xff}"
    xr = request.headers.get("x-real-ip")
    if xr:
        return f"ip:{xr}"
    host = getattr(request.client, "host", None) or "unknown"
    return f"ip:{host}"

def _rate_limit_allow(key: str) -> bool:
    if RL_LIMIT <= 0:
        return True
    now = time.time()
    dq = _rl_cache.get(key)
    if dq is None:
        dq = deque()
        _rl_cache[key] = dq
    # נקה פריטים ישנים
    boundary = now - RL_WINDOW_SEC
    while dq and dq[0] < boundary:
        dq.popleft()
    if len(dq) >= RL_LIMIT:
        return False
    dq.append(now)
    return True

def _record_ai_metric(status: str, start: float) -> None:
    dur = max(0.0, time.time() - start)
    # העדפה: אובייקט מהמידלוור (אם קיים)
    if metrics_exporter and hasattr(metrics_exporter, "record_ai_call"):
        try:
            metrics_exporter.record_ai_call(status=status, latency=dur)
            return
        except Exception:
            pass
    # גיבוי: המודול הישיר
    if me:
        try:
            me.record_ai_call(status=status, latency=dur)
        except Exception:
            pass

def _naive_sentiment(text: str) -> tuple[str, float, float, str]:
    """
    מנתח בסיסי ללא תלות בספק חיצוני:
    מחזיר (sentiment, confidence[0..1], score[-1..1], notes)
    """
    t = text.lower()
    bull = ("bull", "breakout", "buy", "long", "uptrend", "pump", "support hold", "accumulate")
    bear = ("bear", "breakdown", "sell", "short", "downtrend", "dump", "resistance reject", "distribute")
    b_hits = sum(1 for k in bull if k in t)
    s_hits = sum(1 for k in bear if k in t)
    total = b_hits + s_hits
    if total == 0:
        return "neutral", 0.35, 0.0, "No strong directional keywords"
    if b_hits > s_hits:
        conf = min(0.9, 0.55 + 0.1 * (b_hits - s_hits))
        score = min(1.0, 0.15 * (b_hits - s_hits))
        return "bullish", conf, score, f"bullish_hits={b_hits}, bearish_hits={s_hits}"
    if s_hits > b_hits:
        conf = min(0.9, 0.55 + 0.1 * (s_hits - b_hits))
        score = -min(1.0, 0.15 * (s_hits - b_hits))
        return "bearish", conf, score, f"bearish_hits={s_hits}, bullish_hits={b_hits}"
    # tie
    return "neutral", 0.4, 0.0, f"tie_hits={b_hits}"

# ────────────────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────────────────
@router.get("/ping", summary="AI ping", include_in_schema=False)
async def ai_ping():
    return {"ok": True, "ts_ms": int(time.time() * 1000), "enabled": bool(AI_ANALYZE_ENABLE)}

@router.post(
    "/analyze",
    response_model=AnalyzeOut,
    summary="נתח טקסט/קונטקסט והחזר סנטימנט בסיסי (shim)",
    responses={
        429: {"description": "Rate limit"},
        503: {"description": "AI analyze disabled"},
    },
)
async def ai_analyze(request: Request, payload: AnalyzeIn):
    t0 = time.time()

    if not AI_ANALYZE_ENABLE:
        _record_ai_metric("disabled", t0)
        raise HTTPException(status_code=503, detail="AI analyze disabled by config (AI_ANALYZE_ENABLE=0)")

    key = _client_key(request)
    if not _rate_limit_allow(key):
        _record_ai_metric("rate_limited", t0)
        raise HTTPException(status_code=429, detail="Too many requests")

    txt = (payload.text or "").strip()
    if not txt:
        _record_ai_metric("bad_request", t0)
        raise HTTPException(status_code=400, detail="text is required")

    if len(txt) > MAX_TEXT_CHARS:
        txt = txt[:MAX_TEXT_CHARS]

    # ניתוח בסיסי (ללא ספק חיצוני) — מיידי
    try:
        sentiment, confidence, score, notes = _naive_sentiment(txt)
        out = AnalyzeOut(
            ok=True,
            ts_ms=int(time.time() * 1000),
            symbol=(payload.symbol.upper() if payload.symbol else None),
            sentiment=sentiment,
            confidence=float(confidence),
            score=float(score),
            notes=notes,
        )
        _record_ai_metric("ok", t0)
        return out
    except Exception as e:
        logger.exception("ai_analyze failed: %s", e)
        _record_ai_metric("error", t0)
        raise HTTPException(status_code=500, detail="analysis failed")



