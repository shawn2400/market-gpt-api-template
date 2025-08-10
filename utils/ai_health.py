# utils/ai_health.py
# בדיקת בריאות ישירה ל-OpenAI באמצעות HTTP (ללא ה-SDK),
# עם תמיכה ב-OPENAI_BASE_URL, פרוקסי דרך ENV, ו-timeout מסודר.

import os
import asyncio
import json
from typing import Dict, Any, Optional

import aiohttp

# קריאת הגדרות (אם יש utils.config – עדיף)
try:
    from utils import config
    _MODEL = getattr(config, "OPENAI_MODEL", "gpt-4o-mini")
    _BASE_URL: Optional[str] = getattr(config, "OPENAI_BASE_URL", None)
except Exception:
    _MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    _BASE_URL = os.getenv("OPENAI_BASE_URL") or None

# נקודת קצה: ברירת מחדל OpenAI הרשמי; אם יש OPENAI_BASE_URL – נבנה נתיב סטנדרטי.
def _build_api_url() -> str:
    if _BASE_URL:
        base = _BASE_URL.rstrip("/")
        # מניחים ספק תואם OpenAI (כמו OpenRouter וכו') שבו "/v1/chat/completions" קיים
        return f"{base}/v1/chat/completions"
    return "https://api.openai.com/v1/chat/completions"

def _clean(val: str | None) -> str:
    return (val or "").strip().replace("\r", "").replace("\n", "")

async def ping_openai(timeout_sec: int = 6) -> Dict[str, Any]:
    """
    בדיקת בריאות פשוטה ל-OpenAI:
      - מחזירה ok/status/latency_ms/תוכן/שגיאה.
      - מכבדת OPENAI_BASE_URL אם הוגדר.
      - משתמשת ב-aiohttp עם trust_env=True כדי לכבד פרוקסי מ-ENV (HTTP(S)_PROXY).
    """
    api_key = _clean(os.getenv("OPENAI_API_KEY"))
    if not api_key:
        return {"ok": False, "error": "OPENAI_API_KEY missing"}

    url = _build_api_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "AlgoGPT/2 (Render) ai-health",
        "Accept": "application/json",
    }
    payload = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }

    t0 = asyncio.get_event_loop().time()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        # trust_env=True => מכבד HTTP_PROXY / HTTPS_PROXY מהסביבה
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as sess:
            async with sess.post(url, headers=headers, json=payload) as r:
                lat_ms = round((asyncio.get_event_loop().time() - t0) * 1000.0, 1)
                text = await r.text()
                if r.status == 200:
                    try:
                        data = json.loads(text)
                        reply = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                    except Exception:
                        reply = None
                    return {
                        "ok": True,
                        "status": r.status,
                        "latency_ms": lat_ms,
                        "model": _MODEL,
                        "base_url_custom": bool(_BASE_URL),
                        "reply": reply,
                    }
                # נחזיר גוף מקוצר לזיהוי 401/404/429 וכו'
                return {
                    "ok": False,
                    "status": r.status,
                    "latency_ms": lat_ms,
                    "base_url_custom": bool(_BASE_URL),
                    "body": text[:1000],
                }
    except asyncio.TimeoutError:
        lat_ms = round((asyncio.get_event_loop().time() - t0) * 1000.0, 1)
        return {
            "ok": False,
            "error": f"timeout>{timeout_sec}s",
            "latency_ms": lat_ms,
            "base_url_custom": bool(_BASE_URL),
        }
    except Exception as e:
        lat_ms = round((asyncio.get_event_loop().time() - t0) * 1000.0, 1)
        return {
            "ok": False,
            "error": str(e),
            "latency_ms": lat_ms,
            "base_url_custom": bool(_BASE_URL),
        }

