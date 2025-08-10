# utils/ai_client.py
# שכבת לקוח יציבה ל-OpenAI: timeout, ריטריי, קונקרנציה, Proxy נכון (דרך httpx), JSON-mode אופציונלי

import os
import time
import asyncio
import logging
from typing import Optional, Dict, Any

import httpx
from openai import AsyncOpenAI
from openai import APIError, RateLimitError, APITimeoutError, APIStatusError, APIConnectionError

# --- טעינת קונפיג (אם אין utils.config, נעשה fallback קל) ---
try:
    from utils import config
except Exception:  # fallback מינימלי אם אין config
    class _C:
        OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))
        OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "4"))
        OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "") or None
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID", "") or None
        OPENAI_PROJECT = os.getenv("OPENAI_PROJECT", "") or None
        OPENAI_RETRIES = int(os.getenv("OPENAI_RETRIES", "4"))
        OPENAI_LOG_PROMPTS = os.getenv("OPENAI_LOG_PROMPTS", "false").lower() in ("1", "true", "yes", "on")
    config = _C()

# --- קונקרנציה מבוקרת ---
_MAX_CONCURRENCY = int(getattr(config, "OPENAI_MAX_CONCURRENCY", 4))
_semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

# --- סינגלטונים ללקוח וה-HTTPX ---
_httpx_client: Optional[httpx.AsyncClient] = None
_openai_client: Optional[AsyncOpenAI] = None

# מצב משתנה של המודל (ניתן לעדכון בזמן ריצה אם צריך)
_current_model: str = getattr(config, "OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
_default_retries: int = int(getattr(config, "OPENAI_RETRIES", 4))


def _build_httpx_client() -> httpx.AsyncClient:
    """
    בניית httpx.AsyncClient עם Proxy דרך ENV בלבד.
    אל תעביר proxies ישירות ל-AsyncOpenAI — מעבירים http_client מוכן.
    """
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None
    timeout_sec = float(getattr(config, "OPENAI_TIMEOUT_SECONDS", 30.0))
    timeout = httpx.Timeout(timeout_sec)

    headers = {
        "User-Agent": "AlgoGPT/2 (Render) openai-python",
    }

    return httpx.AsyncClient(
        timeout=timeout,
        proxies=proxy,          # יכול להיות None וזה תקין
        headers=headers,
        follow_redirects=True,
        http2=True,
    )


def _ensure_client() -> AsyncOpenAI:
    """
    יוצר/מחזיר AsyncOpenAI כשהוא משתמש ב-httpx client החיצוני.
    """
    global _httpx_client, _openai_client

    if _openai_client is not None:
        return _openai_client

    if _httpx_client is None:
        _httpx_client = _build_httpx_client()

    base_url = getattr(config, "OPENAI_BASE_URL", "") or None
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    org = getattr(config, "OPENAI_ORG_ID", "") or os.getenv("OPENAI_ORG_ID", "") or None
    project = getattr(config, "OPENAI_PROJECT", "") or os.getenv("OPENAI_PROJECT", "") or None

    if not api_key:
        logging.error("[AI] OPENAI_API_KEY is missing")

    _openai_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        organization=org,
        project=project,
        http_client=_httpx_client,  # ← מונע את שגיאת 'proxies' בבנאי
    )
    logging.info("[AI] AsyncOpenAI ready (model=%s, base_url=%s, org=%s, project=%s)",
                 _current_model,
                 ("custom" if base_url else "default"),
                 "yes" if org else "no",
                 "yes" if project else "no")
    return _openai_client


def set_model(model: str) -> None:
    """עדכון דינמי של המודל לשימוש בברירת מחדל."""
    global _current_model
    m = (model or "").strip()
    if not m:
        return
    _current_model = m
    logging.info("[AI] default model switched to: %s", _current_model)


def get_client() -> AsyncOpenAI:
    """החזרת הלקוח (לשימושים מתקדמים מחוץ למודול)."""
    return _ensure_client()


async def _chat_once(
    prompt: str,
    *,
    system: Optional[str],
    model: str,
    temperature: float,
    max_tokens: int,
    response_json: bool,
) -> str:
    """
    שיחה בודדת מול המודל.
    אם response_json=True נבקש JSON mode (במודלים התומכים).
    """
    client = _ensure_client()

    messages = (
        [{"role": "system", "content": system}] if system else []
    ) + [{"role": "user", "content": prompt}]

    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if response_json:
        # JSON mode (רק במודלים התומכים; אם לא — ה-API יתעלם או יכשיל)
        kwargs["response_format"] = {"type": "json_object"}

    if getattr(config, "OPENAI_LOG_PROMPTS", False):
        logging.debug("[AI] prompt(len=%d), system=%s, model=%s, json=%s",
                      len(prompt), bool(system), model, response_json)

    resp = await client.chat.completions.create(**kwargs)
    content = (resp.choices[0].message.content or "").strip()
    return content


def _backoff(attempt: int, base: float = 0.6, cap: float = 8.0) -> float:
    import random
    delay = min(cap, base * (2 ** attempt)) + random.uniform(0, 0.35)
    return delay


async def chat(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 300,
    retries: Optional[int] = None,
    json_mode: bool = False,
) -> str:
    """
    קריאת צ'אט מאובטחת עם ריטריי ל-429/5xx/Timeout/חיבור.
    - json_mode=True יבקש JSON-mode (במודלים התומכים).
    """
    mdl = (model or _current_model).strip()
    attempts = int(_default_retries if retries is None else retries)

    async with _semaphore:
        last_err: Optional[Exception] = None
        for attempt in range(attempts + 1):
            try:
                return await _chat_once(
                    prompt,
                    system=system,
                    model=mdl,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_json=json_mode,
                )
            except (RateLimitError, APITimeoutError, APIConnectionError, httpx.TimeoutException) as e:
                last_err = e
                d = _backoff(attempt)
                logging.warning(f"[AI] transient (attempt {attempt+1}/{attempts+1}) → sleep {d:.2f}s: {e}")
                await asyncio.sleep(d)
            except APIStatusError as e:
                # 5xx → ריטריי
                status = getattr(e, "status_code", None)
                if status and int(status) >= 500 and attempt < attempts:
                    d = _backoff(attempt)
                    logging.warning(f"[AI] API 5xx (attempt {attempt+1}/{attempts+1}) → sleep {d:.2f}s: {e}")
                    await asyncio.sleep(d)
                    last_err = e
                    continue
                logging.error(f"[AI] APIStatusError non-retryable: {e}")
                raise
            except APIError as e:
                # שגיאה כללית — אם אין סטטוס 5xx נסמן כלא בר־ריטריי
                status = getattr(e, "status_code", None)
                if status and int(status) >= 500 and attempt < attempts:
                    d = _backoff(attempt)
                    logging.warning(f"[AI] API 5xx (attempt {attempt+1}/{attempts+1}) → sleep {d:.2f}s: {e}")
                    await asyncio.sleep(d)
                    last_err = e
                    continue
                logging.error(f"[AI] APIError non-retryable: {e}")
                raise
            except Exception as e:
                logging.error(f"[AI] unexpected error: {type(e).__name__}: {e}")
                raise

        if last_err:
            raise last_err
        raise RuntimeError("AI chat failed without explicit exception")


async def ai_healthcheck() -> Dict[str, Any]:
    """
    בדיקת בריאות/לטנסי: פינג קצר עם max_tokens=1.
    לא מפיל שרת — רק מחזיר מצב.
    """
    t0 = time.perf_counter()
    try:
        res = await chat(
            "Reply with OK",
            system="You are a healthcheck probe.",
            temperature=0.0,
            max_tokens=1,
            retries=1,
            json_mode=False,
        )
        dt = (time.perf_counter() - t0) * 1000.0
        ok = res.upper().startswith("OK")
        return {
            "ok": bool(ok),
            "latency_ms": round(dt, 1),
            "model": _current_model,
            "base_url": bool(getattr(config, "OPENAI_BASE_URL", "")),
        }
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        return {
            "ok": False,
            "latency_ms": round(dt, 1),
            "error": f"{e.__class__.__name__}: {e}",
        }


async def close():
    """
    סגירה מסודרת של httpx client (לא חובה ב-Render, אבל נקי).
    """
    global _httpx_client
    try:
        if _httpx_client is not None:
            await _httpx_client.aclose()
            _httpx_client = None
    except Exception as e:
        logging.debug(f"[AI] close() ignored: {e}")



