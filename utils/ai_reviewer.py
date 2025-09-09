# utils/ai_reviewer.py
from __future__ import annotations
import os, logging, json, asyncio
from typing import Dict, Any, Optional
import httpx

from utils.telegram_notifier import notify_trade_review

logger = logging.getLogger("algogpt.ai_reviewer")

ENABLE_AI = str(os.getenv("ENABLE_AI_ROUTES", "false")).lower() in ("1","true","yes","on")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

async def _openai_chat(messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 400) -> Optional[str]:
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
            c = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            return c or None
    except Exception as e:
        logger.warning("[ai_reviewer] openai call failed: %s", e)
        return None

def _fallback_review(trade: Dict[str, Any]) -> str:
    sym = trade.get("symbol", "N/A")
    side = trade.get("side", "N/A")
    rr   = trade.get("rr")
    score= trade.get("score")
    hints = trade.get("reasons") or []
    msg = f"[Heuristic] {sym} {side}: "
    if score is not None:
        msg += f"score={score}. "
    if rr is not None:
        msg += f"RR={rr}. "
    if hints:
        msg += "Improve: " + ", ".join(hints[:4])
    else:
        msg += "Looks reasonably aligned with plan."
    return msg

async def review_trade_async(symbol: str, side: str, context: Dict[str, Any], *, to_telegram: bool = True) -> Dict[str, Any]:
    """
    context יכול לכלול:
      - entry/sl/tp, rr, pnl, indicators, reasons, score
    """
    sym = symbol.upper().strip()
    sd  = side.upper().strip()
    sys_prompt = (
        "You are a concise trading reviewer. Return 3-5 short bullets in Hebrew: "
        "מה עבד, מה לא, ומה לשפר בפעם הבאה. אל תתן עצות כלליות; התייחס לערכים שנתנו (RR/ATR/ADX/תזמון)."
    )
    user_ctx = json.dumps(context, ensure_ascii=False)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"סכם ביקורת לטרייד {sym} {sd}:\n{user_ctx}"},
    ]
    text = await _openai_chat(messages)
    if not text:
        text = _fallback_review(context)

    if to_telegram:
        try:
            await notify_trade_review(sym, text)
        except Exception:
            pass

    return {"ok": True, "symbol": sym, "side": sd, "review": text}
