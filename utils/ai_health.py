# utils/ai_health.py
import os
import time
import logging
from typing import Dict, Any, Optional

try:
    from utils.ai_client import chat
except Exception as e:
    chat = None  # type: ignore
    logging.warning("[ai_health] ai_client.chat not available: %s", e)

# מודל ברירת-מחדל: קודם env, אח"כ דיפולט יציב
DEFAULT_MODEL: str = (
    os.getenv("OPENAI_MODEL")
    or os.getenv("OPENAI_CHAT_MODEL")
    or "gpt-4o-mini"
)

async def ping_openai() -> Dict[str, Any]:
    """
    פינג קצר ל-OpenAI/Azure OpenAI לבדיקת קישוריות וזמן תגובה.
    תלוי ב-utils.ai_client.chat שמחזיר טקסט קצר.
    מחזיר מבנה: { ok, latency_ms, model, reply?, error? }
    """
    if chat is None:
        return {"ok": False, "error": "ai_client.chat not available"}

    t0 = time.time()
    try:
        txt: Optional[str] = await chat(
            "ping",
            system="health-check",
            model=DEFAULT_MODEL,  # לא להשאיר None
            temperature=0.0,
            max_tokens=4,
        )
        dt = round((time.time() - t0) * 1000)
        return {
            "ok": True,
            "latency_ms": dt,
            "model": DEFAULT_MODEL,
            "reply": (txt or "").strip()[:32],
        }
    except Exception as e:
        dt = round((time.time() - t0) * 1000)
        logging.warning("[ai_health] ping failed after %d ms: %s", dt, e)
        return {"ok": False, "latency_ms": dt, "model": DEFAULT_MODEL, "error": str(e)}






