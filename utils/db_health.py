# utils/binance_health.py
from __future__ import annotations
import os
import httpx

_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com").rstrip("/")

async def check_binance_ready(timeout: float = 0.8) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.get(f"{_BASE}/fapi/v1/ping")
            if r.status_code == 200:
                return {"ok": True}
            return {"ok": False, "status": r.status_code, "text": r.text[:120]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
