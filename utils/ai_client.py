# utils/ai_client.py
import os
import asyncio
import logging
from typing import Any, Dict

import httpx

OPENAI_BASE = (os.getenv("OPENAI_BASE_URL") or "").strip() or "https://api.openai.com/v1"
OPENAI_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
TIMEOUT = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
# לא משתמשים ב-HTTP/2 כדי לא לדרוש את h2
HTTP2 = False

async def _post_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")
    url = f"{OPENAI_BASE}/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}

    last_err = None
    async with httpx.AsyncClient(timeout=TIMEOUT, http2=HTTP2) as client:
        for attempt in range(3):
            try:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 200:
                    return r.json()
                last_err = f"http={r.status_code} body={r.text[:400]}"
            except Exception as e:
                last_err = str(e)
            await asyncio.sleep(min(2 ** attempt, 5))
    raise RuntimeError(f"OpenAI request failed: {last_err}")

async def chat(
    prompt: str,
    system: str = "Be concise.",
    model: str = OPENAI_MODEL,
    temperature: float = 0.0,
    max_tokens: int = 256,
    retries: int = 2,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = await _post_chat(payload)
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""

async def ai_healthcheck() -> Dict[str, Any]:
    try:
        txt = await chat("ping", system="Reply with 'pong'.", max_tokens=4)
        ok = "pong" in txt.lower() or len(txt) > 0
        return {"ok": ok, "reply": txt}
    except Exception as e:
        logging.warning(f"[ai_health] {e}")
        return {"ok": False, "error": str(e)}




