# utils/trade_execution_core.py

import os
import logging
from utils.ws_fallback import get_price
from utils.binance_trader import binance_futures_trade

PRICE_PROTECT_PCT = float(os.getenv("PRICE_PROTECT_PCT", 0.25))  # אחוז סטיה מותקף

def execute_trade_live(
    symbol, entry, stop, tp, direction,
    leverage=20, budget_usd=100, market_type="futures",
    price_protect_pct=None
):
    """
    הגנת סטיה – מבצע טרייד חי רק אם המחיר באמת עדכני, עם חיתוך סטיות.
    """
    price_protect_pct = price_protect_pct or PRICE_PROTECT_PCT

    try:
        live_price = get_price(symbol)
        if not live_price or live_price <= 0:
            logging.error(f"[TRADE] ❌ מחיר חי לא תקין ל-{symbol}: {live_price}")
            return {"status": "error", "error": "live price unavailable"}

        deviation = abs((live_price - entry) / entry) * 100
        if deviation > price_protect_pct:
            logging.warning(f"[TRADE] ⚠️ סטיית מחיר {deviation:.4f}% בין תוכנית ({entry}) ללייב ({live_price}) – טרייד נחסם!")
            return {
                "status": "error",
                "error": f"price deviation {deviation:.4f}% > {price_protect_pct}%, trade blocked",
                "entry": entry,
                "live_price": live_price
            }

        # ביצוע בפועל – תמיד לפי המחיר הכי עדכני (ולא נתון ישן)
        result = binance_futures_trade(
            symbol=symbol,
            side=direction,  # "LONG" / "SHORT"
            entry=live_price,
            sl=stop,
            tp=tp,
            leverage=leverage,
            budget=budget_usd,
            market_type=market_type
        )
        logging.info(f"[TRADE] {direction} {symbol} בוצע במחיר {live_price} (סטיה {deviation:.4f}%) - תוצאה: {result}")
        return {"status": "success", "result": result}

    except Exception as e:
        logging.error(f"[TRADE] שגיאה בביצוע טרייד {symbol}: {e}")
        return {"status": "error", "error": str(e)}




