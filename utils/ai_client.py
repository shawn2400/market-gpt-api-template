# utils/ai_client.py
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from utils import config

try:
    import httpx
    from openai import AsyncOpenAI
    from openai._exceptions import APIError, RateLimitError, APITimeoutError, AuthenticationError
except Exception as e:
    httpx = None
    AsyncOpenAI = None
    APIError = RateLimitError = APITimeoutError = AuthenticationError = Exception
    logging.error(f"[ai_client] OpenAI/httpx import failed: {e}")

# --------- Globals ----------
_client: Optional["AsyncOpenAI"] = None
_httpx_client: Optional["httpx.AsyncClient"] = None
_sema = asyncio.Semaphore(max(1, config.OPENAI_MAX_CONCURRENCY))

# very simple circuit breaker
_CB_FAILS = 0
_CB_OPEN_UNTIL = 0.0
_CB_THRESHOLD = 5              # אחרי 5 כשלים רצופים פותחים מעגל
_CB_COOLOFF_SEC = 15.0         # חלון קירור

def _circuit_open() -> bool:
    return time.time() < _CB_OPEN_UNTIL

def _trip_circuit():
    global _CB_OPEN_UNTIL, _CB_FAILS
    _CB_FAILS += 1
    if _CB_FAILS >= _CB_THRESHOLD:
        _CB_OPEN_UNTIL = time.time() + _CB_COOLOFF_SEC
        logging.warning("[ai_client] Circuit OPEN for %.1fs after %d failures", _CB_COOLOFF_SEC, _CB_FAILS)

def _reset_circuit():
    global _CB_FAILS, _CB_OPEN_UNTIL
    _CB_FAILS = 0
    _CB_OPEN_UNTIL = 0.0

def _build_httpx_client() -> Optional["httpx.AsyncClient"]:
    if not httpx:
        return None
    # Respect env proxies (HTTPS_PROXY/NO_PROXY), enable HTTP/2, tune limits
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    timeout = httpx.Timeout(
        config.OPENAI_TIMEOUT_SECONDS, connect=min(10.0, config.OPENAI_TIMEOUT_SECONDS),
        read=config.OPENAI_TIMEOUT_SECONDS, write=min(10.0, config.OPENAI_TIMEOUT_SECONDS)
    )
    transport = httpx.AsyncHTTPTransport(http2=True, verify=True)
    return httpx.AsyncClient(limits=limits, timeout=timeout, transport=transport, trust_env=True)

def _build_client() -> Optional["AsyncOpenAI"]:
    if not AsyncOpenAI:
        logging.error("[ai_client] OpenAI SDK not available")
        return None
    if not config.OPENAI_API_KEY:
        logging.error("[ai_client] OPENAI_API_KEY is empty")
        return None

    global _httpx_client
    if _httpx_client is None:
        _httpx_client = _build_httpx_client()

    kwargs: Dict[str, Any] = {"api_key": config.OPENAI_API_KEY}
    if config.OPENAI_BASE_URL:
        kwargs["base_url"] = config.OPENAI_BASE_URL

    if _httpx_client is not None:
        kwargs["http_client"] = _httpx_client  # <-- הדרך התקינה ב-openai==1.30.1

    return AsyncOpenAI(**kwargs)

def get_ai_client() -> Optional["AsyncOpenAI"]:
    global _client
    if _client is None:
        _client = _build_client()
        if _client:
            logging.info("[ai_client] OpenAI client initialized (model=%s, base=%s)",
                         config.OPENAI_MODEL, config.OPENAI_BASE_URL or "api.openai.com")
    return _client

async def _single_call(messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
    client = get_ai_client()
    if not client:
        return {"ok": False, "error": "OpenAI client not initialized", "type": "InitError"}

    resp = await client.chat.completions.create(
        model=model.strip(),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    return {"ok": True, "content": content, "usage": usage, "model": model}

async def ai_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 256,
    max_retries: int = 3,
    backoff_base: float = 0.6,
) -> Dict[str, Any]:
    """
    עטיפה מאוחדת לקריאות Chat:
    - הגבלת מקביליות (Semaphore)
    - Circuit breaker פשוט
    - ריטריי עם backoff + כיבוד Retry-After כשיש
    - מודל גיבוי (OPENAI_FALLBACK_MODEL) אם נכשל
    - Timeout כולל לפי config.OPENAI_TIMEOUT_SECONDS
    """
    mdl = (model or config.OPENAI_MODEL or "gpt-4o-mini").strip()

    if _circuit_open():
        return {"ok": False, "error": "circuit_open", "type": "CircuitOpen"}

    async with _sema:
        last_err: Optional[Exception] = None
        # רצים עם timeout על כל הסבב, כדי לא להתקע
        total_timeout = max(5.0, config.OPENAI_TIMEOUT_SECONDS + 5.0)

        async def _attempts(run_model: str) -> Dict[str, Any]:
            nonlocal last_err
            for attempt in range(max_retries + 1):
                try:
                    res = await _single_call(messages, run_model, temperature, max_tokens)
                    if res.get("ok"):
                        _reset_circuit()
                        # לוג שימוש
                        u = res.get("usage") or {}
                        logging.info("[ai_client] %s: prompt=%s, comp=%s, total=%s",
                                     run_model, u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"))
                        return res
                    last_err = Exception("unknown failure")
                except (RateLimitError, APITimeoutError, APIError) as e:
                    last_err = e
                    retry_after = None
                    try:
                        retry_after = getattr(e, "response", None) and e.response.headers.get("retry-after")
                        retry_after = float(retry_after) if retry_after is not None else None
                    except Exception:
                        retry_after = None
                    delay = retry_after if retry_after else backoff_base * (2 ** attempt)
                    delay = min(delay, 15.0)
                    logging.warning("[ai_client] transient %s (attempt %d/%d) → %.2fs",
                                    type(e).__name__, attempt+1, max_retries+1, delay)
                    await asyncio.sleep(delay)
                except AuthenticationError as e:
                    return {"ok": False, "error": str(e), "type": "AuthenticationError"}
                except Exception as e:
                    last_err = e
                    logging.error("[ai_client] unexpected %s: %s", type(e).__name__, e)
                    break
            return {"ok": False, "error": str(last_err) if last_err else "unknown error", "type": type(last_err).__name__ if last_err else "UnknownError"}

        try:
            return await asyncio.wait_for(_attempts(mdl), timeout=total_timeout)
        except asyncio.TimeoutError:
            last = {"ok": False, "error": "timeout", "type": "Timeout"}
        except Exception as e:
            last = {"ok": False, "error": str(e), "type": type(e).__name__}

        # מודל גיבוי אם הוגדר ושונה מהראשי
        fb = config.OPENAI_FALLBACK_MODEL.strip() if config.OPENAI_FALLBACK_MODEL else ""
        if fb and fb != mdl:
            logging.warning("[ai_client] trying fallback model: %s", fb)
            try:
                return await asyncio.wait_for(_attempts(fb), timeout=total_timeout)
            except Exception as e:
                last = {"ok": False, "error": str(e), "type": type(e).__name__}

        _trip_circuit()
        return last

async def ai_healthcheck() -> Dict[str, Any]:
    start = time.time()
    res = await ai_chat(
        messages=[{"role": "user", "content": "Reply with: OK"}],
        temperature=0.0,
        max_tokens=4,
        max_retries=2,
        backoff_base=0.5,
    )
    dt = time.time() - start
    if res.get("ok"):
        return {"ok": True, "model": res.get("model"), "latency_sec": round(dt, 3)}
    return {"ok": False, "error": res.get("error"), "type": res.get("type")}
