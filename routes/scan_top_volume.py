# routes/scan_top_volume.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query

try:
    from utils.auth import require_bearer_token
except Exception as e:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter(prefix="/scan", tags=["Scan"], dependencies=[Depends(require_bearer_token)])

# נסיון לייבא את הלוגיקה—אם חסר, נחזיר 503 ולא נפיל ראוטר
_HAS_TOP_VOLUME = True
_scan_top_volume = None
try:
    # נסה קודם את החבילה utils.top_volume (תיקיה עם __init__.py)
    from utils.top_volume import scan_top_volume as _scan_top_volume  # type: ignore
except Exception:
    _HAS_TOP_VOLUME = False
    _scan_top_volume = None

@router.get("/top-volume")
async def scan_top_volume_route(
    market: str = Query("futures", pattern="^(futures|spot)$"),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=200),
    timeframe: str = Query("15m"),
    bars: int = Query(200, ge=50, le=1500),
    trending_only: bool = Query(False),
    min_adx: float = Query(20.0, ge=5.0, le=60.0),
    ema_fast: int = Query(21, ge=3, le=200),
    ema_slow: int = Query(50, ge=5, le=400),
    adx_len: int = Query(14, ge=5, le=50),
    st_period: int = Query(10, ge=5, le=50),
    st_factor: float = Query(3.0, ge=1.0, le=10.0),
    ich_conv: int = Query(9, ge=5, le=50),
    ich_base: int = Query(26, ge=10, le=100),
    ich_span_b: int = Query(52, ge=20, le=200),
    ms_lookback: int = Query(5, ge=2, le=20),
    ms_pivot_span: int = Query(3, ge=1, le=10),
    concurrency: int = Query(16, ge=2, le=64),
):
    if not (_HAS_TOP_VOLUME and _scan_top_volume):
        raise HTTPException(status_code=503, detail="top_volume module unavailable")
    # תמיכה בפונקציה sync או async
    fn = _scan_top_volume
    if getattr(fn, "__await__", None):
        return await fn(**locals())
    return fn(**locals())



