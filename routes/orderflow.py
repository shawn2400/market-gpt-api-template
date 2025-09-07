cat > routes/orderflow.py <<'PY'
# routes/orderflow.py
from __future__ import annotations

import asyncio, time, logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, Path, Query, Request, HTTPException

from utils.auth import require_api_key

logger = logging.getLogger("algogpt.routes.orderflow")

# ─────────────────────────────────────────────────────────
# נסיון לטעון את המחשבון; אם נכשל – לא מפיל את השרת
# ─────────────────────────────────────────────────────────
_CALC_OK = True
_CALC_ERR = None
try:
    from utils.orderflow import get_orderflow_snapshot as _calc_orderflow
except Exception as e:
    _CALC_OK = False
    _CALC_ERR = str(e)
    logger.warning("orderflow calc not available: %s", e)

    def _calc_orderflow(symbol: str, *, trades_limit: int, depth_limit: int, cvd_window: int) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": "orderflow_calc_unavailable",
            "reason": _CALC_ERR or "unknown",
            "symbol": symbol,
        }

# ─────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────
# פומבי: פינג ודיבוג קל – בלי API KEY (אם פתוח ב-PUBLIC_PATHS במידלוור)
router_public = APIRouter(tags=["Analytics"])

@router_public.get("/__of_ping", summary="Orderflow ping", response_model=None)
async def of_ping() -> Dict[str, Any]:
    return {
        "ok": True,
        "route": "/__of_ping",
        "calc_loaded": _CALC_OK,
        "version": "1.0",
    }

# מוגן: דורש מפתח API דרך ה־middleware/require_api_key
router = APIRouter(prefix="/orderflow", tags=["Analytics"], dependencies=[Depends(require_api_key)])

# Rate limit פנימי פשוט
_rl_state: Dict[str, list[float]] = {}
def _rl(ip: str, limit: int = 15, window: int = 60) -> bool:
    now = time.time()
    calls = [t for t in _rl_state.get(ip, []) if now - t < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rl_state[ip] = calls
    return True

@router.get("/{symbol}", summary="Orderflow snapshot", response_model=None)
async def get_orderflow(
    request: Request,                                  # <<< לא Optional! פותר את בעיית ה-Pydantic
    symbol: str = Path(..., description="e.g. BTCUSDT"),
    trades_limit: int = Query(800, ge=1, le=1000),
    depth_limit:  int = Query(500, ge=5, le=1000),
    cvd_window:   int = Query(300, ge=1, le=1000),
) -> Dict[str, Any]:
    # RL לפי IP (אם אין – נמשיך בכל זאת)
    ip = None
    try:
        ip = request.client.host if request and request.client else None
    except Exception:
        ip = None
    if ip and not _rl(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        return await asyncio.to_thread(
            _calc_orderflow,
            symbol.upper(),
            trades_limit=trades_limit,
            depth_limit=depth_limit,
            cvd_window=cvd_window,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_orderflow failed")
        raise HTTPException(status_code=500, detail=f"orderflow failed: {e}")
PY












  

