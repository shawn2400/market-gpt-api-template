# utils/liquidity.py
from __future__ import annotations
import os
import httpx

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

async def estimate_slippage(symbol: str, side: str, notional_usd: float, depth_limit: int = 500):
    """
    הערכת סליפג' לפי עומק ספר פקודות:
      - BUY/LONG -> צורכים asks
      - SELL/SHORT -> צורכים bids
    החישוב בכסף (quote): ממלאים עד notional_usd ומחזירים מחיר מילוי ממוצע מול מחיר mid.
    """
    side = side.upper()
    if side not in ("BUY", "SELL", "LONG", "SHORT"):
        return {"ok": False, "error": "side must be BUY/SELL or LONG/SHORT"}
    url = f"{FUTURES_BASE}/fapi/v1/depth"
    async with httpx.AsyncClient(timeout=6) as client:
        r = await client.get(url, params={"symbol": symbol.upper(), "limit": depth_limit})
        r.raise_for_status()
        d = r.json()
    bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
    asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
    if not bids or not asks:
        return {"ok": False, "error": "empty orderbook"}

    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0

    remaining = float(notional_usd)
    filled_quote = 0.0
    filled_base = 0.0
    ladder = asks if side in ("BUY", "LONG") else bids  # קונים מה-asks, מוכרים ל-bids

    for price, qty in ladder:
        level_quote = price * qty
        take_quote = min(remaining, level_quote)
        if take_quote <= 0:
            break
        take_base = take_quote / price
        filled_quote += take_quote
        filled_base += take_base
        remaining -= take_quote
        if remaining <= 1e-9:
            break

    if filled_base <= 0 or remaining > 1e-6:
        return {"ok": False, "error": "insufficient depth for notional"}

    avg = filled_quote / filled_base
    slip = (avg - mid) / mid if side in ("BUY", "LONG") else (mid - avg) / mid

    return {
        "ok": True,
        "symbol": symbol.upper(),
        "side": "BUY" if side in ("BUY", "LONG") else "SELL",
        "notional_usd": float(notional_usd),
        "mid_price": mid,
        "avg_fill_price": avg,
        "slippage_pct": abs(slip) * 100.0,
    }

