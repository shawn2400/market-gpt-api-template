# routes/market.py
# =========================
# REST API לנתוני שוק (Top Volume Symbols)
# כולל אפשרות להחזיר גם מחיר + Funding Rate מה-Cache
# =========================

from __future__ import annotations
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, Query, HTTPException
import asyncio

try:
    from utils.auth import require_bearer_token
except Exception:
    def require_bearer_token():
        raise HTTPException(status_code=401, detail="Unauthorized")

from utils.top_volume import get_top_volume_symbols
from utils.binance_client import get_cached_symbol_info  # ✅ נשתמש ב־Cache

router = APIRouter(
    prefix="/symbols",
    tags=["Analytics"],
    dependencies=[Depends(require_bearer_token)]
)


@router.get(
    "/top-volume",
    summary="Top symbols by volume (Binance)",
    operation_id="getTopVolumeSymbols"
)
async def get_top_volume(
    market: str = Query("futures", enum=["futures", "spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(50, ge=1, le=100),   # ⬅️ מוגבל ל־100 למניעת ResponseTooLarge
    min_quote_volume: float = Query(0.0, ge=0.0),
) -> Dict[str, Any]:
    """
    מחזיר את רשימת המטבעות בעלי מחזור מסחר גבוה ביותר
    (Top Volume) לפי השוק (Futures/Spot).
    """
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
    market: str = Query("futures", enum=["futures", "spot"]),
    quote: str = Query("USDT"),
    limit: int = Query(20, ge=1, le=50),   # ⬅️ הגבלתי ל־50 כדי לא להעמיס
    min_quote_volume: float = Query(0.0, ge=0.0),
) -> Dict[str, Any]:
    """
    מחזיר את רשימת ה-Top Volume symbols + מחיר נוכחי + Funding Rate מתוך ה-Cache.
    אם הסימבול לא קיים ב-Cache → יוחזר רק ה-Volume.
    """
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






