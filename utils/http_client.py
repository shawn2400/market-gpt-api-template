# utils/http_client.py
from __future__ import annotations
import asyncio, random, time
import httpx

DEFAULT_TIMEOUT = 8.0
_MAX_RETRIES = 4

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()

async def get_client() -> httpx.AsyncClient:
    global _client
    async with _lock:
        if _client is None:
            _client = httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                headers={
                    "User-Agent": "AlgoGPT/2 scanner",
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip"
                },
                http2=True
            )
        return _client

async def safe_get(url: str, *, params: dict | None = None) -> httpx.Response:
    """
    GET עם ריטריים חכמים: מכבד 429/418/5xx + Retry-After, עם jitter.
    """
    client = await get_client()
    attempt = 0
    last_exc: Exception | None = None
    while attempt <= _MAX_RETRIES:
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (418, 429, 500, 502, 503, 504):
                ra = resp.headers.get("Retry-After")
                if ra:
                    delay = min(60.0, max(1.0, float(ra)))
                else:
                    base = 0.6 * (2 ** attempt)
                    delay = min(20.0, base + random.uniform(0, 0.5))
                await asyncio.sleep(delay)
            else:
                resp.raise_for_status()
        except Exception as e:
            last_exc = e
            await asyncio.sleep(min(2.0, 0.3 + 0.3 * attempt))
        attempt += 1
    if last_exc:
        raise last_exc
    raise RuntimeError("safe_get failed without exception")
