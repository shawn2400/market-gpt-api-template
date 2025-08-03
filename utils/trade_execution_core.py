# utils/trade_execution_core.py

import logging
import time
from utils.ws_fallback import get_price  # הגנה מתקדמת – בדיקת מחיר עדכני
from utils.binance_trader import binance_futures_trade

def execute_trade_live(symbol, entry, stop, tp, direction, leverage=20, budget_usd=100, market_type="futures"):
    """
    מבצע טרייד חי ב־Binance לפי פרמטרים נתונים.
    לא מריץ אם אין מחיר עדכני (פחות מ־10 שניות).
    מחזיר dict עם תוצאות הביצוע (id, error, status וכו').
    """
    try:
        # בדיקה: מחיר עדכני בלבד!
        price = get_price(symbol, max_age_sec=10)
        if price is None or abs(price - float(entry)) / float(entry) > 0.005:
            logging.error(f"[TRADE] מחיר לא עדכני/לא נמצא/חריג עבור {symbol} – טרייד מבוטל.")
            return {
                "status": "error",
                "error": f"מחיר לא עדכני או לא נמצא ({price}). טרייד לא בוצע."
            }

        # ביצוע הטרייד בפועל
        result = binance_futures_trade(
            symbol=symbol,
            side=direction,     # "LONG" / "SHORT"
            entry=price,        # עדכני מהרגע האחרון בלבד
            sl=stop,
            tp=tp,
            leverage=leverage,
            budget=budget_usd,
            market_type=market_type
        )
        logging.info(f"[TRADE] {direction} {symbol} בוצע במחיר {price} - תוצאה: {result}")
        return {"status": "success", "result": result}

    except Exception as e:
        logging.error(f"[TRADE] שגיאה בביצוע טרייד {symbol}: {e}")
        return {"status": "error", "error": str(e)}


