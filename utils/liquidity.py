# utils/liquidity.py
from __future__ import annotations
import os
import requests
from typing import Dict, Any, Optional, Tuple

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

DEPTH_LIMIT = int(os.getenv("LIQ_DEPTH_LIMIT", "50"))  # 5/10/20/50/100
MAX_SLIPPAGE_PCT = float(os.getenv("LIQ_MAX_SLIPPAGE_PCT", "0.25"))  # אחוז, לדוגמה 0.25%
MIN_DEPTH_NOTIONAL = float(os.getenv("LIQ_MIN_DEPTH_NOTIONAL_USD", "5000"))  # עומק מינימלי בשכבות

def _fetch_depth(symbol: str, limit: int = DEPTH_LIMIT) -> Dict[str, Any]:
    url = f"{FUTURES_BASE}/fapi/v1/depth"
    r = requests.get(url, params={"symbol": symbol.upper(), "limit": limit}, timeout=5)
    r.raise_for_status()
    return r.json()

def _accumulate(levels, qty_usd_target: float, side: str) -> Tuple[float, float]:
    """
    side='buy' → משתמש ב-Asks; side='sell' → משתמש ב-Bids.
    מחזיר (avg_price, filled_usd).
    """
    remain = qty_usd_target
    cost = 0.0
    filled = 0.0
    for price_str, qty_str in levels:
        p = float(price_str); q = float(qty_str)
        # אומדן: notional זמין ברמה זו:
        notional = p * q
        take = min(remain, notional)
        if take <= 0:
            break
        # כמה יחידות קונים/מוכרים ברמה זו
        units = take / p
        cost += units * p
        filled += units * p
        remain -= take
        if remain <= 0:
            break
    avg = (cost / (filled / p)) if filled > 0 else 0.0  # התאמה לנוסחה – משאיר תוצאה עקבית
    # בפועל avg מחיר ממוצע אפקטיבי: cost / units
    units_total = filled / p if p > 0 else 0.0
    avg_effective = (cost / units_total) if units_total > 0 else 0.0
    return avg_effective, filled

def estimate_slippage_pct(symbol: str, side: str, notional_usd: float) -> Optional[float]:
    """
    מעריך סליפג’ אחוזי לנוטיונל נתון. side: 'BUY' או 'SELL' (לפי עסקה).
    """
    if notional_usd <= 0:
        return 0.0
    d = _fetch_depth(symbol)
    bids = d.get("bids") or []
    asks = d.get("asks") or []
    if not bids or not asks:
        return None

    best_bid = float(bids[0][0]); best_ask = float(asks[0][0])
    mid = (best_bid + best_ask) / 2.0 if (best_bid > 0 and best_ask > 0) else None
    if not mid:
        return None

    if side.upper() == "BUY":
        avg_px, filled_usd = _accumulate(asks, notional_usd, "buy")
    else:
        avg_px, filled_usd = _accumulate(bids, notional_usd, "sell")

    if filled_usd < min(notional_usd, MIN_DEPTH_NOTIONAL):
        # אין מספיק עומק ריאלי
        return None

    slip = (avg_px - mid) / mid * 100.0 if side.upper() == "BUY" else (mid - avg_px) / mid * 100.0
    return max(0.0, slip)

def liquidity_gate(symbol: str, side: str, notional_usd: float) -> Dict[str, Any]:
    """
    גייטינג נזילות: מחזיר dict עם pass/fail ונתונים.
    """
    res = {"symbol": symbol.upper(), "side": side.upper(), "notional_usd": notional_usd}
    slip = estimate_slippage_pct(symbol, side, notional_usd)
    res["slippage_pct"] = slip
    if slip is None:
        res["ok"] = False
        res["reason"] = "insufficient_depth"
        return res
    if slip > MAX_SLIPPAGE_PCT:
        res["ok"] = False
        res["reason"] = f"slippage>{MAX_SLIPPAGE_PCT}%"
        return res
    res["ok"] = True
    res["reason"] = "ok"
    return res
