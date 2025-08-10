# utils/ai_client.py
import os
import asyncio
import logging
import atexit
from typing import Any, Dict, Optional

import httpx
from random import random

# ------------------------ ENV / CONFIG ------------------------
OPENAI_BASE: str = (os.getenv("OPENAI_BASE_URL") or "").strip() or "https://api.openai.com/v1"
OPENAI_KEY: str = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL: str = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()

TIMEOUT_SECONDS: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
MAX_CONCURRENCY: int = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))

# http2 דיפולט כבוי; אפשר להדליק דרך ENV
HTTP2: bool = (os.getenv("OPENAI_HTTP2", "false").strip().lower() in ("1", "true", "yes"))

# ניסיונות/בקאוף
MAX_RETRIES: int = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
BACKOFF_BASE: float = float(os.getenv("OPENAI_BACKOFF_BASE", "0.6"))
BACKOFF_CAP: float = float(os.getenv("OPENAI_BACKOFF_CAP", "10.0"))

# ------------------------ SHARED STATE ------------------------
_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()
_sem = asyncio.Semaphore(max(1, MAX_CONCURRENCY))

def _headers() -> Dict[str, str]:
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")
    return {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json",
    }

async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                base_url=OPENAI_BASE.rstrip("/"),
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
    # לניקוי בזמן יציאה (קריאה סינכרונית)
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
        if v.isdigit():
            return float(v)
    except Exception:
        return None
    return None

def _should_retry(status: int) -> bool:
    # 429=rate limit; 5xx=שגיאות זמניות
    return status in (429, 500, 502, 503, 504)

def _backoff(attempt: int) -> float:
    # exp backoff עם jitter קל
    d = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** attempt))
    return d * (0.7 + 0.6 * random())

# ------------------------ LOW-LEVEL CALL ------------------------
async def _post_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    קריאת /chat/completions עם ריטריי מודע ל-429/5xx ו-ReTry-After.
    """
    client = await _get_client()
    last_err: Optional[str] = None
    url = "/chat/completions"  # base_url כבר נקבע ב-AsyncClient

    async with _sem:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.post(url, json=payload)
                if r.status_code == 200:
                    return r.json()

                # החזק הודעת שגיאה קצרה
                body = r.text[:400]
                last_err = f"http={r.status_code} body={body}"

                if _should_retry(r.status_code):
                    retry_after = _retry_after_seconds(r)
                    if retry_after is not None:
                        await asyncio.sleep(min(retry_after, BACKOFF_CAP))
                    else:
                        await asyncio.sleep(_backoff(attempt))
                    continue

                # לא אמור לנסות שוב
                break

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                last_err = f"net={type(e).__name__}: {e}"
                await asyncio.sleep(_backoff(attempt))
                continue
            except Exception as e:
                last_err = f"unexpected={type(e).__name__}: {e}"
                await asyncio.sleep(_backoff(attempt))
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
    """
    מחזיר את ה-content של ההודעה הראשונה. במקרה של ריק/כשל ייזרק RuntimeError.
    """
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }

    # תמיכה בפרמטרים אופציונליים כמו top_p / presence_penalty / frequency_penalty וכו'
    payload.update({k: v for k, v in kwargs.items() if v is not None})

    data = await _post_chat(payload)
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    content = msg.get("content") or ""
    return content

async def ai_healthcheck() -> Dict[str, Any]:
    """
    ברירת מחדל: שולח 'ping' ובודק שמתקבל 'pong' או כל תשובה לא ריקה.
    """
    try:
        txt = await chat("ping", system="Reply with 'pong'.", max_tokens=4, temperature=0.0)
        ok = ("pong" in txt.lower()) or (len(txt.strip()) > 0)
        return {"ok": ok, "reply": txt, "model": OPENAI_MODEL, "http2": HTTP2, "base": OPENAI_BASE}
    except Exception as e:
        logging.warning(f"[ai_health] {e}")
        return {"ok": False, "error": str(e), "model": OPENAI_MODEL, "http2": HTTP2, "base": OPENAI_BASE}

# ------------------------ CLASS (לשילוב עם main.py) ------------------------
class _AIClient:
    """
    עטיפה עם warmup() לשימוש ב-main.py:
        from utils.ai_client import ai_client
        await ai_client.warmup()
        await ai_client.chat(...)  # אופציונלי, אפשר גם להשתמש בפונקציות המודולריות למעלה
    """
    def __init__(self) -> None:
        self._ready = False

    async def warmup(self) -> None:
        """
        בודק מפתח, מרים AsyncClient, מבצע פינג קצר (ללא כישלון גורלי).
        """
        if not OPENAI_KEY:
            raise RuntimeError("OPENAI_API_KEY missing")
        try:
            # פתיחת client והבטחת headers
            await _get_client()
            # פינג עדין (לא זורק כלפי חוץ)
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

# מופע יחיד לייבוא ע"י main.py
ai_client = _AIClient()





