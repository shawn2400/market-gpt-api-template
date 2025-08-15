# utils/ai_health.py
import os
import asyncio
import json
from typing import Dict, Any, Optional

import aiohttp

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def _clean(val: Optional[str]) -> str:
    return (val or "").strip().replace("\r", "").replace("\n", "")

def _shorten(s: str, n: int = 1000) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"

def _detect_mode() -> str:
    base = _clean(os.getenv("OPENAI_BASE_URL"))
    if "azure.com" in base.lower() or "/openai/deployments" in base.lower() or _clean(os.getenv("AZURE_OPENAI_ENDPOINT")):
        return "azure"
    return "openai"

def _build_url_and_headers() -> tuple[str, dict]:
    mode = _detect_mode()

    # --- OpenAI רגיל ---
    if mode == "openai":
        base = _clean(os.getenv("OPENAI_BASE_URL")) or "https://api.openai.com/v1"
        key = _clean(os.getenv("OPENAI_API_KEY"))
        if not key:
            raise RuntimeError("OPENAI_API_KEY missing")
        url = base.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "AlgoGPT/ai_health (+Render)",
        }
        org = _clean(os.getenv("OPENAI_ORG")) or _clean(os.getenv("OPENAI_ORGANIZATION"))
        if org:
            headers["OpenAI-Organization"] = org
        project = _clean(os.getenv("OPENAI_PROJECT"))
        if project:
            headers["OpenAI-Project"] = project
        return url, headers

    # --- Azure OpenAI ---
    endpoint = _clean(os.getenv("AZURE_OPENAI_ENDPOINT")) or _clean(os.getenv("OPENAI_BASE_URL"))
    deployment = _clean(os.getenv("AZURE_OPENAI_DEPLOYMENT"))
    api_version = _clean(os.getenv("AZURE_OPENAI_API_VERSION") or "2024-02-15-preview")
    key = _clean(os.getenv("AZURE_OPENAI_KEY")) or _clean(os.getenv("OPENAI_API_KEY"))
    if not endpoint or not deployment or not key:
        raise RuntimeError("Azure OpenAI env missing: AZURE_OPENAI_ENDPOINT/AZURE_OPENAI_DEPLOYMENT/AZURE_OPENAI_KEY")

    url = endpoint.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    headers = {
        "api-key": key,
        "Content-Type": "application/json",
        "User-Agent": "AlgoGPT/ai_health (+Render)",
    }
    return url, headers

async def ping_openai(timeout_sec: int = 6, retries: int = 1) -> Dict[str, Any]:
    """
    בדיקת בריאות פשוטה ל-OpenAI/Azure:
    - מחזירה ok + reply (אם יש), סטטוס, מזהה בקשה, ושדות רלוונטיים ל-rate limit.
    - trust_env=True מאפשר שימוש אוטומטי ב-HTTP(S)_PROXY.
    - backoff קצר עבור 429/5xx.
    """
    try:
        url, headers = _build_url_and_headers()
    except Exception as e:
        return {"ok": False, "error": str(e), "model": OPENAI_MODEL, "base_url_custom": bool(_clean(os.getenv("OPENAI_BASE_URL")))}

    payload = {
        "model": OPENAI_MODEL,  # ב-Azure לא מזיק להשאיר
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }

    attempt = 0
    last_error: Optional[str] = None

    while attempt <= max(0, retries):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_sec)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as sess:
                async with sess.post(url, headers=headers, json=payload) as r:
                    text = await r.text()
                    meta = {
                        "status": r.status,
                        "x_request_id": r.headers.get("x-request-id") or r.headers.get("apim-request-id"),
                        "rate_remaining": r.headers.get("x-ratelimit-remaining-requests"),
                        "rate_reset": r.headers.get("x-ratelimit-reset-requests"),
                        "model": OPENAI_MODEL,
                        "mode": _detect_mode(),
                        "base_url_custom": bool(_clean(os.getenv("OPENAI_BASE_URL"))),
                    }
                    if r.status == 200:
                        try:
                            data = json.loads(text)
                            reply = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                        except Exception:
                            reply = None
                        return {"ok": True, "reply": reply, **meta}
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

    return {"ok": False, "error": last_error or "unknown", "model": OPENAI_MODEL, "mode": _detect_mode()}



