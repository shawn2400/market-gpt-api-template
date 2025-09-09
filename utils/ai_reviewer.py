# utils/ai_reviewer.py
from __future__ import annotations
import os, logging, json
from typing import Dict, Any, Optional
import asyncio
import httpx

from utils.telegram_notifier import notify_trade_review

logger = logging.getLogger("algogpt.ai_reviewer")

ENABLE_AI = str(os.getenv("AI_REVIEW_ENABLE", os.getenv("ENABLE_AI_ROUTES", "0"))).lower() in ("1","true","yes","on")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MAX_TOKENS = int(os.getenv("AI_REVIEW_MAX_TOKENS", "400"))

async def _openai_chat(messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = MAX_TOKENS) -> Optional[str]:
    if not (ENABLE_AI and OPENAI_KEY and OPENAI_MODEL):
        return None
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    except Exception as e:
        logger.warning("[ai_reviewer] openai call failed: %s", e)
        return None

def _fallback_review(ctx: Dict[str, Any]) -> str:
    sym = ctx.get("symbol", "N/A")
    side = ctx.get("side", "N/A")
    rr   = ctx.get("rr")
    score= ctx.get("score")
    hints = ctx.get("reasons") or []
    msg = f"[Heuristic] {sym} {side}: "
    if score is not None: msg += f"score={score}. "
    if rr is not None:    msg += f"RR={rr}. "
    if hints: msg += "שיפור: " + ", ".join(map(str, hints[:4]))
    else:     msg += "ביצוע סביר מול התוכנית."
    return msg

async def review_trade_async(symbol: str, side: str, context: Dict[str, Any], *, to_telegram: bool = True) -> Dict[str, Any]:
    """
    context יכול לכלול: entry/sl/tp, rr, pnl, indicators, reasons, score, leverage, duration_min, commissions, etc.
    """
    sym = symbol.upper().strip()
    sd  = side.upper().strip()
    sys_prompt = (
        "אתה מבקר טריידים תמציתי. החזר 3–5 בולטים בעברית: מה עבד, מה לא, ומה לשפר בפעם הבאה. "
        "אל תיתן עצות כלליות—התייחס לערכים (RR/ATR/ADX/תזמון/ביצוע). קצר ומדויק."
    )
    user_ctx = json.dumps({**context, "symbol": sym, "side": sd}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": f"סכם ביקורת לטרייד {sym} {sd} (JSON מצורף):\n{user_ctx}"},
    ]
    text = await _openai_chat(messages) or _fallback_review({**context, "symbol": sym, "side": sd})

    if to_telegram:
        try:
            await notify_trade_review(sym, text)
        except Exception:
            pass

    return {"ok": True, "symbol": sym, "side": sd, "review": text}

def review_trade(symbol: str, side: str, context: Dict[str, Any], *, to_telegram: bool = True) -> Dict[str, Any]:
    """
    עטיפה סינכרונית נוחה לשימוש ממקומות sync.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            fut = asyncio.ensure_future(review_trade_async(symbol, side, context, to_telegram=to_telegram))
            # למי שקורא מסביבה רצה—נחזיר placeholder ונרשום לוג.
            logger.info({"event": "ai_review_scheduled", "symbol": symbol})
            return {"ok": True, "scheduled": True, "symbol": symbol}
        return asyncio.run(review_trade_async(symbol, side, context, to_telegram=to_telegram))
    except RuntimeError:
        return asyncio.run(review_trade_async(symbol, side, context, to_telegram=to_telegram))


