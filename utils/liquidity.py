# utils/liquidity.py
from __future__ import annotations
import os
from typing import Dict, Any, Optional, Tuple, List

import httpx

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# Gate params (override via ENV)
LIQ_MAX_SLIPPAGE_PCT = float(os.getenv("LIQ_MAX_SLIPPAGE_PCT", "0.30"))  # % מקס' סליפג' מותר
LIQ_DEPTH_LIMIT       = int(os.getenv("LIQ_DEPTH_LIMIT", "500"))
LIQ_TIMEOUT_SEC       = float(os.getenv("LIQ_TIMEOUT_SEC", "7"))
LIQ_STRICT            = os.getenv("LIQ_STRICT", "1").lower() in ("1", "true", "yes")

# Reusable client
_client: Optional[httpx.AsyncClient] = None
async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(LIQ_TIMEOUT_SEC),
            headers={
                "User-Agent": "AlgoGPT/2 liquidity",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
            limits=httpx.Limits(max_keepalive_connections=16, max_connections=32),
            http2=False,
        )
    return _client


def _ladder_fill_price(
    ladder: List[Tuple[float, float]],  # [(price, qty_base)]
    notional_quote: float,              # כמה quote (למשל USDT) אנחנו רוצים למלא
) -> Tuple[float, float, float]:
    """
    ממלאים quote לאורך הסולם (asks/bids) ומחזירים:
      (avg_price, filled_base, filled_quote)
    אם אין עומק מספיק → avg_price=0, filled_base=0, filled_quote < notional_quote.
    """
    remaining = float(max(0.0, notional_quote))
    filled_quote = 0.0
    filled_base = 0.0

    for price, qty in ladder:
        if remaining <= 0.0:
            break
        level_quote = price * qty
        if level_quote <= 0.0:
            continue
        take_quote = remaining if remaining <= level_quote else level_quote
        take_base = take_quote / price
        filled_quote += take_quote
        filled_base += take_base
        remaining -= take_quote

    avg = (filled_quote / filled_base) if filled_base > 0 else 0.0
    return avg, filled_base, filled_quote


async def estimate_slippage(
    symbol: str,
    side: str,
    notional_usd: float,
    depth_limit: int = LIQ_DEPTH_LIMIT,
) -> Dict[str, Any]:
    """
    הערכת סליפג' לפי עומק ספר פקודות (Binance Futures):
      - BUY/LONG -> צורכים asks
      - SELL/SHORT -> צורכים bids
    נמדד בכסף (quote), מניח ש־USDT≈USD עבור זוגות *USDT.
    """
    s = side.upper().strip()
    if s not in ("BUY", "SELL", "LONG", "SHORT"):
        return {"ok": False, "error": "side must be BUY/SELL or LONG/SHORT"}

    url = f"{FUTURES_BASE}/fapi/v1/depth"
    try:
        client = await _get_client()
        r = await client.get(url, params={"symbol": symbol.upper(), "limit": int(depth_limit)})
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return {"ok": False, "error": f"orderbook_fetch_failed: {e}"}

    try:
        bids = [(float(p), float(q)) for p, q in d.get("bids", []) if float(p) > 0 and float(q) > 0]
        asks = [(float(p), float(q)) for p, q in d.get("asks", []) if float(p) > 0 and float(q) > 0]
    except Exception:
        return {"ok": False, "error": "bad_orderbook_payload"}

    if not bids or not asks:
        return {"ok": False, "error": "empty_orderbook"}

    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0 if (best_bid > 0 and best_ask > 0) else 0.0
    if mid <= 0.0:
        return {"ok": False, "error": "invalid_mid_price"}

    ladder = asks if s in ("BUY", "LONG") else bids  # קונים מן ה־asks, מוכרים אל ה־bids
    avg, filled_base, filled_quote = _ladder_fill_price(ladder, float(notional_usd))

    if filled_quote + 1e-9 < float(notional_usd) or filled_base <= 0:
        return {"ok": False, "error": "insufficient_depth", "mid_price": mid}

    if s in ("BUY", "LONG"):
        slip = (avg - mid) / mid
    else:
        slip = (mid - avg) / mid

    return {
        "ok": True,
        "symbol": symbol.upper(),
        "side": "BUY" if s in ("BUY", "LONG") else "SELL",
        "notional_usd": float(notional_usd),
        "mid_price": mid,
        "avg_fill_price": avg,
        "slippage_pct": abs(slip) * 100.0,
        "filled_base": filled_base,
        "filled_quote": filled_quote,
        "depth_limit": depth_limit,
    }


async def liquidity_gate(
    symbol: str,
    side: str,
    *,
    notional_usd: float,
    max_slippage_pct: Optional[float] = None,
    depth_limit: int = LIQ_DEPTH_LIMIT,
) -> Dict[str, Any]:
    """
    שער נזילות "קשיח-רך": מחשב סליפג' משוער ולא מאשר אם הוא גבוה מן הסף.
    אם LIQ_STRICT=0 ונכשל להביא עומק — נחזיר ok=True עם reason (Fail-Open).
    """
    thr = float(max_slippage_pct if max_slippage_pct is not None else LIQ_MAX_SLIPPAGE_PCT)
    res = await estimate_slippage(symbol, side, notional_usd, depth_limit=depth_limit)

    if not res.get("ok"):
        reason = f"liquidity_probe_failed: {res.get('error')}"
        if LIQ_STRICT:
            return {"ok": False, "reason": reason}
        # מצב Fail-Open
        return {"ok": True, "reason": reason, "slippage_pct": None}

    slip = float(res.get("slippage_pct") or 0.0)
    if slip <= thr:
        return {"ok": True, "slippage_pct": slip, "reason": f"slippage {slip:.3f}% <= {thr:.3f}%"}
    return {"ok": False, "slippage_pct": slip, "reason": f"slippage {slip:.3f}% > {thr:.3f}%"}

