# utils/ai_client.py
import os
import asyncio
import logging
import atexit
from typing import Any, Dict, Optional, Tuple

import httpx
from random import random

# ------------------------ ENV / CONFIG ------------------------
OPENAI_BASE: str = (os.getenv("OPENAI_BASE_URL") or "").strip() or "https://api.openai.com/v1"
OPENAI_KEY: str = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL: str = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
OPENAI_ORG: Optional[str] = (os.getenv("OPENAI_ORG") or "").strip() or None
OPENAI_PROJECT: Optional[str] = (os.getenv("OPENAI_PROJECT") or "").strip() or None

# --- Azure OpenAI (optional) ---
AZURE_ENDPOINT: str = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
AZURE_KEY: str = (os.getenv("AZURE_OPENAI_KEY") or "").strip()
AZURE_DEPLOYMENT: str = (os.getenv("AZURE_OPENAI_DEPLOYMENT") or "").strip()
AZURE_API_VERSION: str = (os.getenv("AZURE_OPENAI_API_VERSION") or "2024-02-15-preview").strip()

# Shared knobs
TIMEOUT_SECONDS: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
MAX_CONCURRENCY: int = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))
HTTP2: bool = (os.getenv("OPENAI_HTTP2", "false").strip().lower() in ("1", "true", "yes"))

# Retries / backoff
MAX_RETRIES: int = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
BACKOFF_BASE: float = float(os.getenv("OPENAI_BACKOFF_BASE", "0.6"))
BACKOFF_CAP: float = float(os.getenv("OPENAI_BACKOFF_CAP", "10.0"))

# ------------------------ MODE DETECTION ------------------------
def _detect_mode() -> Tuple[str, str]:
    base_lower = (OPENAI_BASE or "").lower()
    if (AZURE_ENDPOINT and AZURE_KEY and AZURE_DEPLOYMENT) or ("azure.com" in base_lower) or ("/openai/deployments" in base_lower):
        base = AZURE_ENDPOINT or OPENAI_BASE
        return "azure", base.rstrip("/")
    return "openai", OPENAI_BASE.rstrip("/")

_MODE, _BASE = _detect_mode()

# ------------------------ SHARED STATE ------------------------
_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()
_sem = asyncio.Semaphore(max(1, MAX_CONCURRENCY))

def _headers() -> Dict[str, str]:
    if _MODE == "azure":
        key = AZURE_KEY or OPENAI_KEY
        if not key:
            raise RuntimeError("AZURE_OPENAI_KEY or OPENAI_API_KEY missing for Azure mode")
        return {"api-key": key, "Content-Type": "application/json"}
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")
    hdrs = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    if OPENAI_ORG:
        hdrs["OpenAI-Organization"] = OPENAI_ORG
    if OPENAI_PROJECT:
        hdrs["OpenAI-Project"] = OPENAI_PROJECT
    return hdrs

async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                base_url=_BASE,
                timeout=TIMEOUT_SECONDS,
                http2=HTTP2,
                headers=_headers(),
            )
    return _client

async def _close_client():
    global _client
    if _client is not None and not _client.is_closed:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None

def _close_client_sync():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_close_client())
        else:
            loop.run_until_complete(_close_client())
    except Exception:
        pass

atexit.register(_close_client_sync)

def _retry_after_seconds(resp: httpx.Response) -> Optional[float]:
    try:
        v = resp.headers.get("Retry-After")
        if not v:
            return None
        v = v.strip()
        return float(v) if v.replace(".", "", 1).isdigit() else None
    except Exception:
        return None

def _should_retry(status: int) -> bool:
    return status in (429, 500, 502, 503, 504)

def _backoff(attempt: int) -> float:
    d = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** attempt))
    return d * (0.7 + 0.6 * random())

# ------------------------ URL ROUTING ------------------------
def _chat_endpoint_path() -> str:
    if _MODE == "azure":
        if not AZURE_DEPLOYMENT:
            raise RuntimeError("AZURE_OPENAI_DEPLOYMENT missing for Azure mode")
        return f"/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions"
    return "/chat/completions"

def _chat_query_params() -> Dict[str, str]:
    if _MODE == "azure":
        return {"api-version": AZURE_API_VERSION}
    return {}

# ------------------------ LOW-LEVEL CALL ------------------------
async def _post_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    client = await _get_client()
    last_err: Optional[str] = None
    url = _chat_endpoint_path()
    params = _chat_query_params()

    async with _sem:
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = await client.post(url, json=payload, params=params)
                if r.status_code == 200:
                    return r.json()

                body_snip = (r.text or "")[:400]
                last_err = f"http={r.status_code} body={body_snip}"

                if _should_retry(r.status_code):
                    retry_after = _retry_after_seconds(r)
                    if retry_after is not None:
                        sleep_for = min(retry_after, BACKOFF_CAP) * (0.9 + 0.2 * random())
                        logging.warning(f"[ai_client] 429/5xx (attempt {attempt+1}) → sleep {sleep_for:.2f}s (Retry-After)")
                        await asyncio.sleep(sleep_for)
                    else:
                        bo = _backoff(attempt)
                        logging.warning(f"[ai_client] 429/5xx (attempt {attempt+1}) → backoff {bo:.2f}s")
                        await asyncio.sleep(bo)
                    continue
                break
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                last_err = f"net={type(e).__name__}: {e}"
                bo = _backoff(attempt)
                logging.warning(f"[ai_client] network error (attempt {attempt+1}) → backoff {bo:.2f}s: {e}")
                await asyncio.sleep(bo)
                continue
            except Exception as e:
                last_err = f"unexpected={type(e).__name__}: {e}"
                bo = _backoff(attempt)
                logging.warning(f"[ai_client] unexpected (attempt {attempt+1}) → backoff {bo:.2f}s: {e}")
                await asyncio.sleep(bo)
                continue
    raise RuntimeError(f"OpenAI request failed: {last_err}")

# ------------------------ PUBLIC API ------------------------
async def chat(
    prompt: str,
    system: str = "Be concise.",
    model: str = OPENAI_MODEL,
    temperature: float = 0.0,
    max_tokens: int = 256,
    **kwargs: Any,
) -> str:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    payload.update({k: v for k, v in kwargs.items() if v is not None})

    try:
        data = await _post_chat(payload)
        choices = data.get("choices") or []
        if not choices:
            logging.warning(f"[ai_client] empty choices: {str(data)[:300]}")
            return ""

        choice0 = choices[0]
        # ✅ תמיכה גם ב-message וגם ב-text
        if "message" in choice0:
            return (choice0.get("message") or {}).get("content") or ""
        if "text" in choice0:
            return choice0.get("text") or ""
        return ""
    except Exception as e:
        logging.warning(f"[ai_client.chat] {e}")
        return ""

async def ai_healthcheck() -> Dict[str, Any]:
    try:
        txt = await chat("ping", system="Reply with 'pong'.", max_tokens=8, temperature=0.0)
        reply = (txt or "").strip()
        ok = "pong" in reply.lower() or len(reply) > 0
        return {
            "ok": ok,
            "reply": reply,
            "mode": _MODE,
            "model": OPENAI_MODEL,
            "http2": HTTP2,
            "base": _BASE,
            "org": OPENAI_ORG if _MODE == "openai" else None,
            "project": OPENAI_PROJECT if _MODE == "openai" else None,
            "azure_deployment": AZURE_DEPLOYMENT if _MODE == "azure" else None,
            "azure_api_version": AZURE_API_VERSION if _MODE == "azure" else None,
        }
    except Exception as e:
        logging.warning(f"[ai_health] {e}")
        return {"ok": False, "error": str(e), "model": OPENAI_MODEL, "mode": _MODE}

# ------------------------ CLASS ------------------------
class _AIClient:
    def __init__(self) -> None:
        self._ready = False

    async def warmup(self) -> None:
        try:
            if _MODE == "azure":
                if not (AZURE_KEY or OPENAI_KEY):
                    raise RuntimeError("AZURE_OPENAI_KEY (or OPENAI_API_KEY) missing for Azure mode")
                if not AZURE_DEPLOYMENT:
                    raise RuntimeError("AZURE_OPENAI_DEPLOYMENT missing")
            else:
                if not OPENAI_KEY:
                    raise RuntimeError("OPENAI_API_KEY missing")
            await _get_client()
            try:
                res = await ai_healthcheck()
                self._ready = bool(res.get("ok", False))
            except Exception:
                self._ready = False
        except Exception as e:
            logging.warning(f"[ai_client.warmup] {e}")
            self._ready = False

    async def chat(self, *args, **kwargs) -> str:
        return await chat(*args, **kwargs)

    @property
    def ready(self) -> bool:
        return self._ready

    async def close(self) -> None:
        await _close_client()

ai_client = _AIClient()










