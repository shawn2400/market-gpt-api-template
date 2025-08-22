# routes/market.py
# =========================
# REST API לנתוני שוק (Top Volume Symbols)
# כולל Rate-Limit, שימוש ב־Cache למחירים ו-Funding
# =========================

from __future__ import annotations
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, Query, HTTPException, Request
import asyncio, time

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.top_volume import get_top_volume_symbols
from utils.binance_client import get_cached_symbol_info

router = APIRouter(
    prefix="/symbols",
    tags=["Analytics"],
    dependencies=[Depends(require_bearer_token)]
)

# =========================
# Rate Limit פנימי (למניעת הצפות)
# =========================
_rate_limit_state: Dict[str, list] = {}

def check_rate_limit(ip: str, limit: int, window: int = 60) -> bool:
    now = time.time()
    calls = _rate_limit_state.get(ip, [])
    # נשמור רק קריאות מהדקה האחרונה
    calls = [c for c in calls if now - c < window]
    if len(calls) >= limit:
        return False
    calls.append(now)
    _rate_limit_state[ip] = calls
    return True

# =========================
# Endpoints
# =========================
@router.get(
    "/top-volume",
    summary="Top symbols by volume (Binance)",
    operation_id="getTopVolumeSymbols"
)
async def get_top_volume(
    request: Request,
    market: str = Query("futures", enum=["futures", "spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=100),   # ⬅️ מוגבל ל־100
    min_quote_volume: float = Query(0.0, ge=0.0),
) -> Dict[str, Any]:
    ip = request.client.host
    if not check_rate_limit(ip, limit=20, window=60):  # ⬅️ מקסימום 20 קריאות בדקה
        raise HTTPException(status_code=429, detail="Rate limit exceeded (20 per 60s)")

    try:
        ok, symbols = await asyncio.to_thread(
            get_top_volume_symbols,
            market,
            quote,
            limit,
            min_quote_volume
        )
        return {
            "ok": bool(ok),
            "market": market,
            "quote": quote,
            "limit": limit,
            "symbols": symbols or []
        }
    except Exception as e:
        return {
            "ok": False,
            "market": market,
            "quote": quote,
            "limit": limit,
            "symbols": [],
            "error": str(e)
        }


@router.get(
    "/top-volume-with-prices",
    summary="Top symbols with markPrice + fundingRate (from cache)",
    operation_id="getTopVolumeWithPrices"
)
async def get_top_volume_with_prices(
    request: Request,
    market: str = Query("futures", enum=["futures", "spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(20, ge=1, le=50),   # ⬅️ מוגבל ל־50 כדי לא להעמיס
    min_quote_volume: float = Query(0.0, ge=0.0),
) -> Dict[str, Any]:
    ip = request.client.host
    if not check_rate_limit(ip, limit=30, window=60):  # ⬅️ מקסימום 30 קריאות בדקה
        raise HTTPException(status_code=429, detail="Rate limit exceeded (30 per 60s)")

    try:
        ok, symbols = await asyncio.to_thread(
            get_top_volume_symbols,
            market,
            quote,
            limit,
            min_quote_volume
        )

        enriched: List[Dict[str, Any]] = []
        for sym in symbols or []:
            info = get_cached_symbol_info(sym["symbol"]) or {}
            enriched.append({
                **sym,
                "price": info.get("price"),
                "fundingRate": info.get("fundingRate"),
                "nextFundingTime": info.get("nextFundingTime"),
                "ts": info.get("ts")
            })

        return {
            "ok": True,
            "market": market,
            "quote": quote,
            "limit": limit,
            "symbols": enriched
        }
    except Exception as e:
        return {
            "ok": False,
            "market": market,
            "quote": quote,
            "limit": limit,
            "symbols": [],
            "error": str(e)
        }








