# utils/ai_health.py
import time
import logging
from typing import Dict, Any

try:
    from utils.ai_client import chat
except Exception as e:
    chat = None
    logging.warning("[ai_health] ai_client.chat not available: %s", e)

async def ping_openai() -> Dict[str, Any]:
    """
    פינג קצר ל־OpenAI (או Azure OpenAI אם מוגדר ב-client) לבדיקת קישוריות וזמני תגובה.
    """
    if chat is None:
        return {"ok": False, "error": "ai_client.chat not available"}

    t0 = time.time()
    try:
        txt = await chat(
            "ping",
            system="health-check",
            model=None,           # שימוש בדיפולט של ה-client
            temperature=0.0,
            max_tokens=4,
        )
        dt = round((time.time() - t0) * 1000)
        return {
            "ok": True,
            "latency_ms": dt,
            "reply": (txt or "").strip()[:32],
        }
    except Exception as e:
        dt = round((time.time() - t0) * 1000)
        logging.warning("[ai_health] ping failed after %d ms: %s", dt, e)
        return {"ok": False, "latency_ms": dt, "error": str(e)}




