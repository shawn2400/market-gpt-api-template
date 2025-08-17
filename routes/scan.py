# routes/scan.py
from __future__ import annotations

import os
import asyncio
from typing import List, Dict, Any, Optional, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query

# ---- Auth (עם fallback) ----
try:
    from utils.auth import require_bearer_token  # type: ignore
except Exception:
    def require_bearer_token():
        return None

from utils.scanner_utils import analyze_symbol, scan_all
from utils.top_volume import get_top_volume_symbols

# ---- Semaphore (עם fallback דיפולטי) ----
try:
    from utils.semaphore_manager import get_semaphore  # type: ignore
except Exception:
    _SEM: Optional[asyncio.Semaphore] = None
    def get_semaphore(name: str = "scan", default_concurrency: int = 8) -> asyncio.Semaphore:
        global _SEM
        if _SEM is None:
            _SEM = asyncio.Semaphore(int(os.getenv("SCAN_CONCURRENCY", default_concurrency)))
        return _SEM

router = APIRouter(
    tags=["Scan"],
    dependencies=[Depends(require_bearer_token)],
)

# ---------- Models (פשוטים) ----------
class ScanSingleRequest(Dict[str, Any]): ...
class ScanMultiRequest(Dict[str, Any]): ...

# ---------- GET /scan (heartbeat) ----------
@router.get("/scan", summary="Scanner heartbeat / info")
async def get_scan_info():
    return {
        "ok": True,
        "endpoints": ["/scan", "/scan/top-volume", "/scan/multi"],
        "defaults": {
            "timeframe": "15m",
            "limit": 150,
            "top_volume_limit": int(os.getenv("TOP_VOLUME_LIMIT", "50")),
            "quote": os.getenv("TOP_VOLUME_QUOTE", "USDT"),
            "concurrency": int(os.getenv("SCAN_CONCURRENCY", "8")),
        },
    }

# ---------- GET /scan/top-volume ----------
@router.get("/scan/top-volume", summary="Top volume symbols (USDT by default)")
async def get_top_volume(
    limit: int = Query(default=int(os.getenv("TOP_VOLUME_LIMIT", "50")), ge=1, le=200),
    quote: str = Query(default=os.getenv("TOP_VOLUME_QUOTE", "USDT")),
):
    symbols = await get_top_volume_symbols(quote=quote, limit=limit)
    return {
        "ok": True,
        "count": len(symbols),
        "quote": quote.upper(),
        "limit": limit,
        "symbols": symbols,
    }

# ---------- POST /scan (single) ----------
@router.post("/scan", summary="Run single-symbol scan")
async def post_scan_single(payload: ScanSingleRequest = Body(...)):
    sym = str(payload.get("symbol") or "").upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")
    tf = str(payload.get("timeframe") or payload.get("interval") or "15m")
    limit = int(payload.get("limit") or 150)

    res = await analyze_symbol(sym, timeframe=tf, limit=limit)
    if not res:
        return {"ok": True, "count": 0, "signals": []}
    return {"ok": True, "count": 1, "signals": [res]}

# ---------- POST /scan/multi ----------
@router.post("/scan/multi", summary="Run multi-symbol scan (with Top-Volume support)")
async def post_scan_multi(payload: ScanMultiRequest = Body(...)):
    """
    גוף הבקשה תומך בשתי דרכים:
      1) {"symbols": ["BTCUSDT", "ETHUSDT"], "timeframe":"15m", "limit":150}
      2) {"top_volume": true, "top_limit": 50, "quote":"USDT", "timeframe":"15m", "limit":150}
    """
    tf = str(payload.get("timeframe") or payload.get("interval") or "15m")
    limit = int(payload.get("limit") or 150)

    symbols: List[str] = [s for s in (payload.get("symbols") or []) if (s or "").strip()]
    use_top = bool(payload.get("top_volume") or False)
    top_limit = int(payload.get("top_limit") or int(os.getenv("TOP_VOLUME_LIMIT", "50")))
    quote = str(payload.get("quote") or os.getenv("TOP_VOLUME_QUOTE", "USDT")).upper()

    if use_top or not symbols:
        symbols = await get_top_volume_symbols(quote=quote, limit=top_limit)

    if not symbols:
        return {"ok": True, "count": 0, "signals": []}

    # אסינכרון עם הגבלת קונקרנציה
    sem = get_semaphore("scan", int(os.getenv("SCAN_CONCURRENCY", "8")))
    async def _task(sym: str):
        async with sem:
            try:
                return await analyze_symbol(sym, timeframe=tf, limit=limit)
            except Exception:
                return None

    tasks = [_task(s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    signals = [r for r in results if isinstance(r, dict) and r]

    return {"ok": True, "count": len(signals), "signals": signals}



