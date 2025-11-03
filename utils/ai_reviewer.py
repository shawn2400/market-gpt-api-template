# utils/ai_reviewer.py
from __future__ import annotations
import os, logging, json, asyncio, time
from typing import Dict, Any, Optional
import httpx
from collections import deque

# notify_trade_review not available in telegram_notifier
# from utils.telegram_notifier import notify_trade_review

logger = logging.getLogger("algogpt.ai_reviewer")

ENABLE_AI_ROUTES = str(os.getenv("ENABLE_AI_ROUTES", "false")).lower() in ("1","true","yes","on")
AI_REVIEW_ENABLE = str(os.getenv("AI_REVIEW_ENABLE", "1")).lower() in ("1","true","yes","on")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

RATE_PER_MIN = int(os.getenv("AI_REVIEW_RATE_PER_MIN", "12"))
MAX_TOKENS   = int(os.getenv("AI_REVIEW_MAX_TOKENS", "400"))
IDEMP_TTL    = float(os.getenv("AI_REVIEW_IDEMP_TTL_SEC", "900"))

try:
    from prometheus_client import Counter
    _C_REVIEWS           = Counter("ai_reviews_total", "Total trade reviews attempted")
    _C_OPENAI_CALLS      = Counter("ai_reviews_openai_calls_total", "OpenAI calls")
    _C_RATE_LIMITED      = Counter("ai_reviews_rate_limited_total", "Reviews rate-limited")
    _C_DEDUP_SKIPPED     = Counter("ai_reviews_dedup_skipped_total", "Reviews dedup skipped")
    _C_FALLBACK_USED     = Counter("ai_reviews_fallback_used_total", "Heuristic fallback used")
except Exception:
    class _N:
        def inc(self, *a, **k): pass
    _C_REVIEWS=_C_OPENAI_CALLS=_C_RATE_LIMITED=_C_DEDUP_SKIPPED=_C_FALLBACK_USED=_N()

_rl_hits = deque()  # timestamps (sec)
_seen: Dict[str, float] = {}

def _rl_allow() -> bool:
    now = time.time()
    while _rl_hits and now - _rl_hits[0] > 60.0:
        _rl_hits.popleft()
    if len(_rl_hits) >= RATE_PER_MIN:
        return False
    _rl_hits.append(now)
    return True

def _idempotent_key(symbol: str, side: str, context: Dict[str, Any]) -> str:
    oid = str(context.get("order_id") or context.get("exec_id") or context.get("close_ts") or "")
    return f"{symbol.upper()}|{side.upper()}|{oid}"

def _idempotent_seen(key: str) -> bool:
    now = time.time()
    for k, ts in list(_seen.items()):
        if now - ts > IDEMP_TTL:
            _seen.pop(k, None)
    if key in _seen:
        return True
    _seen[key] = now
    return False

async def _openai_chat(messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = MAX_TOKENS) -> Optional[str]:
    if not (ENABLE_AI_ROUTES and AI_REVIEW_ENABLE and OPENAI_KEY and OPENAI_MODEL):
        return None
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {"model": OPENAI_MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        _C_OPENAI_CALLS.inc()
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            return (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception as e:
        logger.warning("[ai_reviewer] openai call failed: %s", e)
        return None

def _fallback_review(trade: Dict[str, Any]) -> str:
    _C_FALLBACK_USED.inc()
    sym = trade.get("symbol", "N/A")
    side = trade.get("side", "N/A")
    rr   = trade.get("rr")
    score= trade.get("score")
    hints = trade.get("reasons") or []
    msg = f"[Heuristic] {sym} {side}: "
    if score is not None: msg += f"score={score}. "
    if rr is not None:    msg += f"RR={rr}. "
    if hints:             msg += "Improve: " + ", ".join(hints[:4])
    else:                 msg += "נראה סביר מול התכנית."
    return msg

async def review_trade_async(symbol: str, side: str, context: Dict[str, Any], *, to_telegram: bool = True) -> Dict[str, Any]:
    _C_REVIEWS.inc()
    sym, sd = symbol.upper().strip(), side.upper().strip()
    key = _idempotent_key(sym, sd, context or {})
    if _idempotent_seen(key):
        _C_DEDUP_SKIPPED.inc()
        return {"ok": True, "symbol": sym, "side": sd, "review": None, "skipped": "dedup"}

    use_openai = _rl_allow()
    sys_prompt = (
        "You are a concise trading reviewer. Return 3-5 short bullets in Hebrew: "
        "מה עבד, מה לא, ומה לשפר בפעם הבאה. אל תתן עצות כלליות; התייחס לערכים שנתנו (RR/ATR/ADX/תזמון/סטטוס)."
    )
    user_ctx = json.dumps(context or {}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"סכם ביקורת לטרייד {sym} {sd}:\n{user_ctx}"},
    ]

    text: Optional[str] = None
    if use_openai:
        text = await _openai_chat(messages)
    else:
        _C_RATE_LIMITED.inc()

    if not text:
        text = _fallback_review({"symbol": sym, "side": sd, **(context or {})})

    if to_telegram and text:
        try:
            from utils.alerts import send_telegram_message
            await send_telegram_message(f"📝 Review: {sym}\n{text}", parse_mode="HTML")
        except Exception:
            pass

    return {"ok": True, "symbol": sym, "side": sd, "review": text}




