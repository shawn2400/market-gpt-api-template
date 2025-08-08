# utils/ai_health.py
import os
import asyncio
import json
from typing import Dict, Any

import aiohttp

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
# ניתן להגדיר מודל דרך ENV; ברירת מחדל יציבה וזולה
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _clean(val: str | None) -> str:
    """ניקוי אנטרים/רווחים מיותרים ממפתחות ENV."""
    return (val or "").strip().replace("\r", "").replace("\n", "")


async def ping_openai(timeout_sec: int = 6) -> Dict[str, Any]:
    """
    בדיקת בריאות פשוטה ל-OpenAI:
    - מחזירה ok/status/body/שגיאה לצורכי דיבוג.
    - לא תלויה ב-SDK הרשמי; שימוש ישיר ב-HTTP.
    """
    api_key = _clean(os.getenv("OPENAI_API_KEY"))
    if not api_key:
        return {"ok": False, "error": "OPENAI_API_KEY missing"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.post(OPENAI_API_URL, headers=headers, json=payload) as r:
                text = await r.text()
                if r.status == 200:
                    try:
                        data = json.loads(text)
                        reply = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                    except Exception:
                        reply = None
                    return {"ok": True, "status": r.status, "model": OPENAI_MODEL, "reply": reply}
                # נחזיר גוף מקוצר לזיהוי 401/404/429 וכו'
                return {"ok": False, "status": r.status, "body": text[:1000]}
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout>{timeout_sec}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
