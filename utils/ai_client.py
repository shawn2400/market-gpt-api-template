# utils/ai_client.py
# שכבת לקוח יציבה ל-OpenAI: timeout, ריטריי, קונקרנציה, Proxy נכון (דרך httpx)
import os
import time
import asyncio
import logging
from typing import Optional, Dict, Any

import httpx
from openai import AsyncOpenAI
from openai import APIError, RateLimitError, APITimeoutError

from utils import config

# --- קונקרנציה מבוקרת ---
_MAX_CONCURRENCY = int(getattr(config, "OPENAI_MAX_CONCURRENCY", 4))
_semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

# --- סינגלטון לקוחות ---
_httpx_client: Optional[httpx.AsyncClient] = None
_openai_client: Optional[AsyncOpenAI] = None

def _build_httpx_client() -> httpx.AsyncClient:
    # אל תעביר proxies ל-AsyncOpenAI ישירות; העבר אותם ל-httpx.AsyncClient
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None

    timeout_sec = float(getattr(config, "OPENAI_TIMEOUT_SECONDS", 30.0))
    timeout = httpx.Timeout(timeout_sec)

    headers = {
        "User-Agent": "AlgoGPT/2 (Render) openai-python",
        # אל תכניס כאן Authorization
    }

    return httpx.AsyncClient(
        timeout=timeout,
        proxies=proxy,          # יכול להיות None — וזה תקין
        headers=headers,
        follow_redirects=True,
        http2=True,
    )

def _ensure_client() -> AsyncOpenAI:
    global _httpx_client, _openai_client

    if _openai_client is not None:
        return _openai_client

    if _httpx_client is None:
        _httpx_client = _build_httpx_client()

    base_url = getattr(config, "OPENAI_BASE_URL", "") or None
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")

    if not api_key:
        logging.error("[AI] OPENAI_API_KEY is missing")
    _openai_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=_httpx_client,  # ← זה המפתח נגד השגיאה של proxies
    )
    return _openai_client

async def _chat_once(
    prompt: str,
    *,
    system: Optional[str],
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    client = _ensure_client()
    resp = await client.chat.completions.create(
        model=model,
        messages=(
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
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
    retries: int = 4,
) -> str:
    """
    קריאת צ'אט מאובטחת עם ריטריי ל-429/5xx/Timeout.
    """
    mdl = model or getattr(config, "OPENAI_MODEL", "gpt-4o-mini")

    async with _semaphore:
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                return await _chat_once(
                    prompt, system=system, model=mdl,
                    temperature=temperature, max_tokens=max_tokens
                )
            except (RateLimitError, APITimeoutError) as e:
                last_err = e
                d = _backoff(attempt)
                logging.warning(f"[AI] rate/timeout (attempt {attempt+1}/{retries+1}) → sleep {d:.2f}s: {e}")
                await asyncio.sleep(d)
            except APIError as e:
                # שגיאות 5xx לרוב ניתנות לריטריי
                status = getattr(e, "status_code", None)
                if status and int(status) >= 500 and attempt < retries:
                    d = _backoff(attempt)
                    logging.warning(f"[AI] API 5xx (attempt {attempt+1}/{retries+1}) → sleep {d:.2f}s: {e}")
                    await asyncio.sleep(d)
                    last_err = e
                    continue
                logging.error(f"[AI] APIError non-retryable: {e}")
                raise
            except httpx.TimeoutException as e:
                last_err = e
                d = _backoff(attempt)
                logging.warning(f"[AI] httpx timeout (attempt {attempt+1}/{retries+1}) → sleep {d:.2f}s")
                await asyncio.sleep(d)
            except Exception as e:
                # חריגה לא צפויה — אל תסתיר
                logging.error(f"[AI] unexpected error: {type(e).__name__}: {e}")
                raise
        # אם הגענו לכאן — אזלנו ריטריי
        if last_err:
            raise last_err
        raise RuntimeError("AI chat failed without explicit exception")

async def ai_healthcheck() -> Dict[str, Any]:
    """
    בריאות/לטנסי: פינג קצר עם max_tokens=1.
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
        )
        dt = (time.perf_counter() - t0) * 1000.0
        ok = res.upper().startswith("OK")
        return {
            "ok": bool(ok),
            "latency_ms": round(dt, 1),
            "model": getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
            "base_url": bool(getattr(config, "OPENAI_BASE_URL", "")),
        }
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000.0
        return {
            "ok": False,
            "latency_ms": round(dt, 1),
            "error": str(e.__class__.__name__) + ": " + str(e),
        }

async def close():
    """
    סגירה מסודרת של httpx client (לרוב לא קריטי ב-Render, אבל נקי).
    """
    global _httpx_client
    try:
        if _httpx_client is not None:
            await _httpx_client.aclose()
            _httpx_client = None
    except Exception as e:
        logging.debug(f"[AI] close() ignored: {e}")

__all__ = ["chat", "ai_healthcheck", "close"]

