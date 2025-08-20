from __future__ import annotations
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime, timezone
import asyncio, os
from fastapi import APIRouter, Depends, Query, Header

# ---- Auth ----
try:
    from utils.auth import require_bearer_token as _raw_require_bearer
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return _raw_require_bearer(authorization=authorization)
except Exception:
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return None

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])
MAX_ITEMS = int(os.getenv("SCAN_MAX_LIMIT", "10"))

async def _analyze_one(symbol: str, interval: str, market: str, bars: int = 200) -> Dict[str, Any]:
    sym = symbol.upper().strip()
    try:
        from utils.multi_tf_scanner import analyze_symbol
        return await analyze_symbol(symbol=sym, interval=interval, market_type=market, bars=bars)
    except Exception as e:
        return {"symbol": sym, "reason": f"analyze-fallback: {type(e).__name__}"}

@router.get("/info")
def get_scan_info():
    now = datetime.now(tz=timezone.utc).isoformat()
    return {"ok": True, "now_utc": now}

@router.get("")
async def get_scan(
    symbols: Optional[str] = Query(None),
    market_type: Literal["futures", "spot"] = "futures",
    interval: str = "15m",
    top: int = 10,
):
    if top > MAX_ITEMS:
        top = MAX_ITEMS
    from utils.multi_tf_scanner import multi_tf_scan_with_ai
    if symbols:
        syms = [s.strip().upper() for s in symbols.split(",")][:MAX_ITEMS]
        sem = asyncio.Semaphore(16)
        async def _work(sym: str):
            async with sem:
                return await _analyze_one(sym, interval, market_type)
        results = await asyncio.gather(*[_work(s) for s in syms])
        return {"ok": True, "count": len(results), "items": results}
    res = await multi_tf_scan_with_ai(timeframes=(interval, "1h"), markets=(market_type,), min_quality=6, top=top)
    return {"ok": True, "count": len(res or []), "items": res}




























































