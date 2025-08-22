from fastapi import Request
import time

# Rate Limit state
_rate_limit_state: Dict[str, list] = {}

def check_rate_limit(ip: str, limit: int, window: int = 60) -> bool:
    now = time.time()
    calls = _rate_limit_state.get(ip, [])
    # רק קריאות מהדקה האחרונה
    calls = [c for c in calls if now - c < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rate_limit_state[ip] = calls
    return True

# -----------------------------------
# Fresh endpoint (כבר מוגבל 5 לדקה)
@router.get("/fresh")
async def get_symbols_fresh(request: Request, ...):
    ip = request.client.host
    if not check_rate_limit(ip, limit=5, window=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded (5 per 60s)")
    ...
    return {...}

# -----------------------------------
# Top-volume-with-prices (Cache) – נוסיף Limit 30 לדקה
@router.get("/top-volume-with-prices")
async def get_top_volume_with_prices(request: Request, ...):
    ip = request.client.host
    if not check_rate_limit(ip, limit=30, window=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded (30 per 60s)")
    ...
    return {...}







