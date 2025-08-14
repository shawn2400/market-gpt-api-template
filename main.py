# utils/trade_execution_core.py

import os
from typing import Dict, Any, Optional
from utils.ws_fallback import get_price_smart

def _is_live_enabled() -> bool:
    # ניתן לשליטה ע"י משתנה סביבה או קונפיג. ברירת מחדל: DRY-RUN (לא מבצע הזמנות אמיתיות)
    val = os.getenv("LIVE_TRADING", "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    # אלטרנטיבה: כבדיקת קונפיג אם קיים
    try:
        from utils import config
        return bool(getattr(config, "AUTOTRADING_ENABLE", False)) and bool(getattr(config, "AUTOTRADING_EXECUTE", False))
    except Exception:
        return False

async def execute_trade_live(
    symbol: str,
    side: str,                 # "LONG" | "SHORT"
    entry: Optional[float],    # אם None — ניקח מחיר חי
    sl: float,
    tp: float,
    leverage: int,
    budget_usd: float,
    market_type: str = "futures",
) -> Dict[str, Any]:
    """
    ליבה אחידה לביצוע טרייד. ברירת מחדל DRY-RUN.
    אם LIVE_TRADING=true (או בקונפיג AUTOTRADING_ENABLE/EXECUTE), אפשר לשלב כאן מימוש Binance אמיתי.
    """
    side = side.upper()
    if side not in ("LONG", "SHORT"):
        return {"status": "error", "error": f"invalid side: {side}"}

    live_price = await get_price_smart(symbol)
    price = float(entry) if entry is not None else (float(live_price) if live_price else 0.0)
    if price <= 0:
        return {"status": "error", "error": "price unavailable"}

    # כרגע: DRY-RUN בטוח — מחזיר תוכנית ביצוע ותוצאות סימולציה
    if not _is_live_enabled():
        return {
            "status": "success",
            "result": {
                "mode": "DRY_RUN",
                "symbol": symbol.upper(),
                "side": side,
                "entry": price,
                "sl": float(sl),
                "tp": float(tp),
                "leverage": int(leverage),
                "budget_usd": float(budget_usd),
                "market_type": market_type,
            },
        }

    # אם תרצה LIVE אמיתי, אפשר להרחיב כאן:
    # 1) לבחור צד (BUY/SELL) לפי LONG/SHORT
    # 2) לחשב כמות לפי תקציב ומינוף/גודל חוזה
    # 3) להציב הזמנת MARKET/STOP/TAKE_PROFIT וכו'
    # כרגע נחזיר תשובה מאומתת בלי ביצוע (placeholder):
    return {
        "status": "success",
        "result": {
            "mode": "LIVE_PLACEHOLDER",
            "symbol": symbol.upper(),
            "side": side,
            "entry": price,
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget_usd": float(budget_usd),
            "market_type": market_type,
            "note": "Live trading stub – implement real Binance orders here when ready.",
        },
    }



















































