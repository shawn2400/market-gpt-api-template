# utils/http_client.py
from __future__ import annotations
import os, asyncio, time, random, logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("algogpt.http")

HTTP_TIMEOUT = float(os.getenv("BINANCE_HTTP_TIMEOUT", "8.0"))
HTTP_MAX_RETRIES = int(os.getenv("BINANCE_MAX_RETRIES", "5"))
HTTP_BACKOFF_BASE = float(os.getenv("BINANCE_BACKOFF_BASE", "0.7"))
HTTP_MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", "200"))
HTTP_MAX_KEEPALIVE = int(os.getenv("HTTP_MAX_KEEPALIVE", "100"))
HTTP_CONCURRENCY = int(os.getenv("HTTP_CONCURRENCY", "32"))

CB_WINDOW_SEC = int(os.getenv("CB_WINDOW_SEC", "30"))
CB_FAIL_THRESHOLD = int(os.getenv("CB_FAIL_THRESHOLD", "6"))
CB_OPEN_SEC = int(os.getenv("CB_OPEN_SEC", "20"))

class _CircuitBreaker:
    def __init__(self):
        self.fail_t = []
        self.open_until = 0.0
        self.lock = asyncio.Lock()
    async def before(self):
        async with self.lock:
            now = time.time()
            self.fail_t = [t for t in self.fail_t if now - t <= CB_WINDOW_SEC]
            if now < self.open_until:
                raise RuntimeError("circuit_open")
    async def mark_success(self):
        async with self.lock:
            self.fail_t.clear()
            self.open_until = 0.0
    async def mark_failure(self):
        async with self.lock:
            now = time.time()
            self.fail_t.append(now)
            self.fail_t = [t for t in self.fail_t if now - t <= CB_WINDOW_SEC]
            if len(self.fail_t) >= CB_FAIL_THRESHOLD:
                self.open_until = now + CB_OPEN_SEC
                logger.warning({"event":"circuit_open","open_for_sec":CB_OPEN_SEC,"fails":len(self.fail_t)})

CB = _CircuitBreaker()
def circuit_breaker_open() -> bool:
    return time.time() < CB.open_until

_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()
_sema = asyncio.Semaphore(HTTP_CONCURRENCY)

async def get_client() -> httpx.AsyncClient:
    global _client
    async with _client_lock:
        if _client is None:
            limits = httpx.Limits(max_connections=HTTP_MAX_CONNECTIONS, max_keepalive_connections=HTTP_MAX_KEEPALIVE)
            _client = httpx.AsyncClient(http2=True, limits=limits, timeout=httpx.Timeout(HTTP_TIMEOUT))
        return _client

def _need_retry(status: int) -> bool:
    return status in (408, 409, 425, 429, 500, 502, 503, 504)

async def _safe_call(method: str, url: str, **kwargs) -> httpx.Response:
    if circuit_breaker_open():
        raise RuntimeError("circuit_open")
    await CB.before()
    retries = HTTP_MAX_RETRIES
    backoff = HTTP_BACKOFF_BASE
    async with _sema:
        for attempt in range(retries + 1):
            try:
                cli = await get_client()
                r = await cli.request(method, url, **kwargs)
                if _need_retry(r.status_code):
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                await CB.mark_success()
                return r
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
                await CB.mark_failure()
                if attempt >= retries:
                    logger.warning({"event":"http_giveup","method":method,"url":url,"err":str(e)})
                    raise
                sleep_s = backoff * (1.0 + random.random())
                await asyncio.sleep(sleep_s)
                backoff *= 1.8

async def safe_get(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str,str]] = None):
    return await _safe_call("GET", url, params=params, headers=headers)

async def safe_post(url: str, json: Optional[Dict[str, Any]] = None, data: Any = None, headers: Optional[Dict[str,str]] = None):
    return await _safe_call("POST", url, json=json, headers=headers, data=data)

async def safe_delete(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str,str]] = None):
    return await _safe_call("DELETE", url, params=params, headers=headers)


