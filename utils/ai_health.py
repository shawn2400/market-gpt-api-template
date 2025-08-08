# utils/ai_health.py
import os, asyncio, json
import aiohttp

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
# בחר מודל קיים אצלך. אם אינך בטוח, gpt-4o-mini יציב וזול.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def _clean(val: str | None) -> str:
    return (val or "").strip().replace("\r", "").replace("\n", "")

async def ping_openai(timeout_sec: int = 6) -> dict:
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
                # נחזיר תמיד גוף תגובה לזיהוי 401/429 וכו'
                if r.status == 200:
                    data = json.loads(text)
                    msg = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                    return {"ok": True, "status": r.status, "model": OPENAI_MODEL, "reply": msg}
                else:
                    return {"ok": False, "status": r.status, "body": text[:1000]}
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout>{timeout_sec}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
