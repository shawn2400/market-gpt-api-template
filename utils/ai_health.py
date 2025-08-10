# utils/ai_health.py
import os
import asyncio
import json
from typing import Dict, Any, Optional

import aiohttp

# ניתן להגדיר מודל/בסיס דרך ENV
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def _clean(val: Optional[str]) -> str:
    """ניקוי אנטרים/רווחים מיותרים ממפתחות ENV."""
    return (val or "").strip().replace("\r", "").replace("\n", "")

def _shorten(s: str, n: int = 1000) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"

def _build_url() -> str:
    base = _clean(os.getenv("OPENAI_BASE_URL"))  # למשל פרוקסי תואם OpenAI
    if base:
        # נוודא שאין סלאש כפול
        return base.rstrip("/") + "/chat/completions"
    return "https://api.openai.com/v1/chat/completions"

async def ping_openai(timeout_sec: int = 6, retries: int = 1) -> Dict[str, Any]:
    """
    בדיקת בריאות פשוטה ל-OpenAI ב-HTTP ישיר (לא תלוי SDK):
    - ok/status/reply + מזהה בקשה/ratelimit אם זמינים.
    - תומך בפרוקסי דרך ENV (HTTP[S]_PROXY) עם trust_env=True.
    - ניסיון חוזר קצר עבור 429/5xx.
    """
    api_key = _clean(os.getenv("OPENAI_API_KEY"))
    if not api_key:
        return {"ok": False, "error": "OPENAI_API_KEY missing"}

    url = _build_url()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "AlgoGPT/ai_health (+Render)",
    }
    org = _clean(os.getenv("OPENAI_ORG")) or _clean(os.getenv("OPENAI_ORGANIZATION"))
    if org:
        headers["OpenAI-Organization"] = org
    project = _clean(os.getenv("OPENAI_PROJECT"))
    if project:
        headers["OpenAI-Project"] = project

    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }

    attempt = 0
    last_error: Optional[str] = None

    while attempt <= max(0, retries):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_sec)
            # trust_env=True מאפשר שימוש אוטומטי ב-HTTP(S)_PROXY מהסביבה
            async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as sess:
                async with sess.post(url, headers=headers, json=payload) as r:
                    text = await r.text()
                    meta = {
                        "status": r.status,
                        "x_request_id": r.headers.get("x-request-id"),
                        "rate_remaining": r.headers.get("x-ratelimit-remaining-requests"),
                        "rate_reset": r.headers.get("x-ratelimit-reset-requests"),
                        "model": OPENAI_MODEL,
                        "base_url_custom": bool(_clean(os.getenv("OPENAI_BASE_URL"))),
                    }
                    if r.status == 200:
                        try:
                            data = json.loads(text)
                            reply = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                        except Exception:
                            reply = None
                        return {"ok": True, "reply": reply, **meta}
                    # טיפול רך ב-429/5xx עם backoff קצר
                    if r.status in (429, 500, 502, 503, 504) and attempt < retries:
                        await asyncio.sleep(min(6.0, 0.6 * (2 ** attempt)))
                        attempt += 1
                        continue
                    return {"ok": False, "body": _shorten(text), **meta}
        except asyncio.TimeoutError:
            last_error = f"timeout>{timeout_sec}s"
        except Exception as e:
            last_error = str(e)

        if attempt < retries:
            await asyncio.sleep(min(6.0, 0.6 * (2 ** attempt)))
            attempt += 1
        else:
            break

    return {"ok": False, "error": last_error or "unknown"}


