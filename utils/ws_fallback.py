# utils/ws_fallback.py
from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Optional
import httpx

# רוטציית דומיינים – תואם ל-binance_client
FAPI_POOL: List[str] = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]

HTTP_TIMEOUT = float(__import__("os").getenv("BINANCE_HTTP_TIMEOUT_SEC", "6.0"))

def _client_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    }

async def _get_json_with_rotation(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for idx, base in enumerate(FAPI_POOL):
        url = f"{base}{path}"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, http2=True, headers=_client_headers()) as x:
                r = await x.get(url, params=params)
            # בדיקת HTML/403 – אם כן, ננסה דומיין אחר
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 403 or "text/html" in ct.lower():
                last_err = RuntimeError(f"CloudFront 403/HTML from {url}")
                await asyncio.sleep(0.25 * (idx + 1))
                continue
            r.raise_for_status()
            j = r.json()
            if isinstance(j, dict):
                return j
            return {"data": j}
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.25 * (idx + 1))
            continue
    if last_err:
        raise last_err
    raise RuntimeError("rotation failed with no error?")

async def get_price(symbol: str) -> float:
    """מחזיר Mark Price אמין עם רוטציה וריטריים (REST)."""
    sym = symbol.upper()
    for attempt in range(3):
        try:
            j = await _get_json_with_rotation("/fapi/v1/premiumIndex", params={"symbol": sym})
            price = float(j.get("markPrice") or 0.0)
            if price > 0:
                return price
        except Exception:
            await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch price for {sym}")
















