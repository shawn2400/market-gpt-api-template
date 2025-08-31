# utils/liquidity.py
from __future__ import annotations
import os
import asyncio
import httpx
from typing import Dict, Any, Optional, Tuple

from utils.watchlist_utils import is_top10

FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# ספי היגיון פשוטים (היוריסטיקה מהירה שלא שוברת event loop)
LIQ_MAX_NOTIONAL_TOP10   = float(os.getenv("LIQ_MAX_NOTIONAL_TOP10", "200000"))
LIQ_MAX_NOTIONAL_OTHERS  = float(os.getenv("LIQ_MAX_NOTIONAL_OTHERS", "50000"))

# (אופציונלי) אם תבחר להפעיל בדיקת סליפג' אמיתית — ראו הערות ב-liquidity_gate
SLIPPAGE_MAX_PCT_TOP10   = float(os.getenv("SLIPPAGE_MAX_PCT_TOP10", "0.40"))
SLIPPAGE_MAX_PCT_OTHERS  = float(os.getenv("SLIPPAGE_MAX_PCT_OTHERS", "0.80"))
LIQ_USE_SLIPPAGE         = os.getenv("LIQ_USE_SLIPPAGE", "0").lower() in ("1","true","yes")


async def estimate_slippage(symbol: str, side: str, notional_usd: float, depth_limit: int = 500) -> Dict[str, Any]:
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


def _heuristic_liquidity_ok(symbol: str, notional_usd: float) -> Tuple[bool, str]:
    cap = LIQ_MAX_NOTIONAL_TOP10 if is_top10(symbol) else LIQ_MAX_NOTIONAL_OTHERS
    if notional_usd <= cap:
        return True, f"heuristic ok: notional ${notional_usd:.2f} ≤ cap ${cap:.2f}"
    return False, f"heuristic fail: notional ${notional_usd:.2f} > cap ${cap:.2f}"


def liquidity_gate(symbol: str, side: str, *, notional_usd: float) -> Dict[str, Any]:
    """
    שער נזילות מהיר ובטוח להפעלה מתוך קורוטינה קיימת (הוורקר).
    ברירת מחדל: היגיון היוריסטי בלבד (אינו עושה I/O).

    אפשר להפעיל בדיקת סליפג' אמיתית עם LIQ_USE_SLIPPAGE=1.
    שים לב: בתוך event loop אין להריץ asyncio.run; לכן כאן ננסה
    להריץ בדיקה אסינכרונית *רק אם אין* event loop פעיל. אחרת נישאר עם היוריסטיקה.
    """
    ok, reason = _heuristic_liquidity_ok(symbol, float(notional_usd))
    out = {"ok": ok, "reason": reason, "method": "heuristic"}

    if not LIQ_USE_SLIPPAGE:
        return out

    # נסיון להריץ בדיקת סליפג' רק אם אין event loop רץ (כדי לא לתקוע את הוורקר)
    try:
        asyncio.get_running_loop()
        # יש לופ רץ → לא נבצע I/O כאן
        out["reason"] += " (slippage check skipped: running loop)"
        return out
    except RuntimeError:
        pass  # אין לופ → אפשר להריץ

    try:
        res = asyncio.run(estimate_slippage(symbol, side, notional_usd))
        if not res.get("ok"):
            out.update({"ok": ok, "reason": f"{reason}; slippage_check_error: {res.get('error')}", "method": "heuristic"})
            return out

        slip = float(res.get("slippage_pct") or 0.0)
        thr = SLIPPAGE_MAX_PCT_TOP10 if is_top10(symbol) else SLIPPAGE_MAX_PCT_OTHERS
        if slip <= thr:
            return {
                **res,
                "ok": True,
                "reason": f"slippage {slip:.2f}% ≤ {thr:.2f}%",
                "method": "slippage",
            }
        return {
            **res,
            "ok": False,
            "reason": f"slippage {slip:.2f}% > {thr:.2f}%",
            "method": "slippage",
        }
    except Exception as e:
        out["reason"] += f" (slippage check failed: {e})"
        return out


