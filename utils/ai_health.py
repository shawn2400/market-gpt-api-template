# utils/ai_health.py
import os
import time
import logging
from typing import Dict, Any

try:
    from utils.ai_client import chat
except Exception as e:
    chat = None
    logging.warning("[ai_health] ai_client.chat not available: %s", e)

# בחירת מודל: קודם כל מהסביבה, אחרת דיפולט יציב
DEFAULT_MODEL = (
    os.getenv("OPENAI_MODEL")
    or os.getenv("OPENAI_CHAT_MODEL")
    or "gpt-4o-mini"
)

async def ping_openai() -> Dict[str, Any]:
    """
    פינג קצר ל־OpenAI (או Azure OpenAI אם מוגדר ב-client) לבדיקת קישוריות וזמן תגובה.
    דורש שהסביבה תכיל OPENAI_API_KEY, ובמידה וה-client מחייב מודל – נספק דיפולט.
    """
    if chat is None:
        return {"ok": False, "error": "ai_client.chat not available"}

    t0 = time.time()
    try:
        txt = await chat(
            "ping",
            system="health-check",
            model=DEFAULT_MODEL,   # ✅ חשוב: לא להשאיר None
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





