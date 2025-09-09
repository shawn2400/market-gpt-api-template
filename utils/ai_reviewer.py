# utils/ai_reviewer.py
from __future__ import annotations
import os, logging, json
from typing import Dict, Any, Optional, List

import httpx
from utils.telegram_notifier import notify_trade_review

logger = logging.getLogger("algogpt.ai_reviewer")

# דגלי הפעלה מה-ENV (שני שמות כדי להיות תואם להגדרות השונות)
AI_REVIEW_ENABLE = str(os.getenv("AI_REVIEW_ENABLE", "1")).lower() in ("1", "true", "yes", "on")
ENABLE_AI_ROUTES = str(os.getenv("ENABLE_AI_ROUTES", "0")).lower() in ("1", "true", "yes", "on")
AI_ON = AI_REVIEW_ENABLE or ENABLE_AI_ROUTES

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

async def _openai_chat(messages: List[Dict[str, str]],
                       *,
                       temperature: float = 0.2,
                       max_tokens: int = 400) -> Optional[str]:
    """קריאת Chat Completions. מחזירה טקסט או None."""
    if not (AI_ON and OPENAI_KEY and OPENAI_MODEL):
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
            return (data.get("choices") or [{}])[0].get("message", {}).get("content") or None
    except Exception as e:
        logger.warning("[ai_reviewer] openai call failed: %s", e)
        return None

def _fallback_review(ctx: Dict[str, Any]) -> str:
    """ביקורת בסיסית כש-AI לא זמין."""
    sym = ctx.get("symbol", "N/A")
    side = ctx.get("side", "N/A")
    rr   = ctx.get("rr")
    score= ctx.get("score")
    hints = ctx.get("reasons") or []
    msg = f"[Heuristic] {sym} {side}: "
    if score is not None:
        msg += f"score={score}. "
    if rr is not None:
        msg += f"RR={rr}. "
    if hints:
        msg += "Improve: " + ", ".join([str(h) for h in hints][:4])
    else:
        msg += "Looks reasonably aligned with plan."
    return msg

async def review_trade_async(symbol: str,
                             side: str,
                             context: Dict[str, Any],
                             *,
                             to_telegram: bool = True) -> Dict[str, Any]:
    """
    מפיק ביקורת קצרה בעברית על טרייד שנסגר.
    context יכול לכלול: entry/sl/tp/exit, rr, pnl_usd, indicators (ATR/ADX/RSI/MACD), reasons, score, timing וכו'.
    """
    sym = (symbol or "").upper().strip()
    sd  = (side or "").upper().strip()

    sys_prompt = (
        "You are a concise trading reviewer. Return 3-5 short bullets in Hebrew: "
        "מה עבד, מה לא, ומה לשפר בפעם הבאה. אל תחזור על הנתונים; תן מסקנות ישימות, "
        "תתייחס ספציפית ל-RR/ATR/ADX/תזמון/כניסה-יציאה/ניהול SL/TP."
    )
    user_ctx = json.dumps({"symbol": sym, "side": sd, **(context or {})}, ensure_ascii=False)

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"סכם ביקורת לטרייד {sym} {sd}:\n{user_ctx}"},
    ]

    text = await _openai_chat(messages)
    if not text:
        # נפילה ל-heu כש-AI לא זמין
        text = _fallback_review({"symbol": sym, "side": sd, **(context or {})})

    if to_telegram:
        try:
            await notify_trade_review(sym, text)
        except Exception:
            # לא לשבור ריצה בגלל טלגרם
            pass

    return {"ok": True, "symbol": sym, "side": sd, "review": text}

