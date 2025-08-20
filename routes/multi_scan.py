# routes/multi_scan.py
from __future__ import annotations
from typing import List, Dict, Any, Optional, Literal, Iterable
from datetime import datetime, timezone
import asyncio
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header

# ---- Auth ----
try:
    from utils.auth import require_bearer_token as _raw_require_bearer
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return _raw_require_bearer(authorization=authorization)
except Exception:
    def require_bearer_token(authorization: Optional[str] = Header(default=None)):
        return None

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

def _cfg(name: str, default: Any) -> Any:
    try:
        from utils import config
        return getattr(config, name, default)
    except Exception:
        return default

def _is_executor_running() -> bool:
    try:
        from utils.auto_executor import is_executor_running
        return bool(is_executor_running())
    except Exception:
        return False

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
    cfg = {
        "AUTO_RUN": bool(_cfg("AUTO_RUN", False)),
        "SCAN_INTERVAL": int(_cfg("SCAN_INTERVAL", 60)),
        "MIN_QUALITY_SCORE": float(_cfg("MIN_QUALITY_SCORE", 6)),
    }
    return {"ok": True, "now_utc": now, "executor_running": _is_executor_running(), "config": cfg}

@router.get("")
async def get_scan(
    symbols: Optional[str] = Query(None),
    market_type: Literal["futures", "spot"] = "futures",
    interval: str = "15m",
    top: int = 10,
):
    from utils.multi_tf_scanner import multi_tf_scan_with_ai
    items: List[Dict[str, Any]] = []
    if symbols:
        syms = [s.strip().upper() for s in symbols.split(",")]
        sem = asyncio.Semaphore(16)
        async def _work(sym: str):
            async with sem:
                return await _analyze_one(sym, interval, market_type)
        results = await asyncio.gather(*[_work(s) for s in syms])
        return {"ok": True, "count": len(results), "items": results}
    res = await multi_tf_scan_with_ai(timeframes=(interval, "1h"), markets=(market_type,), min_quality=6, top=top)
    return {"ok": True, "count": len(res or []), "items": res}



























































