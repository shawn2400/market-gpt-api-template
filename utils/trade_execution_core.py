# utils/trade_execution_core.py

import logging
from utils.binance_trader import binance_futures_trade

def execute_trade_live(symbol, entry, stop, tp, direction, leverage=20, budget_usd=100, market_type="futures"):
    """
    מבצע טרייד חי ב־Binance לפי פרמטרים נתונים.
    מחזיר dict עם תוצאות הביצוע (id, error, status וכו')
    """
    try:
        result = binance_futures_trade(
            symbol=symbol,
            side=direction,     # "LONG" / "SHORT"
            entry=entry,
            sl=stop,
            tp=tp,
            leverage=leverage,
            budget=budget_usd,
            market_type=market_type
        )
        logging.info(f"[TRADE] {direction} {symbol} בוצע במחיר {entry} - תוצאה: {result}")
        return {"status": "success", "result": result}
    except Exception as e:
        logging.error(f"[TRADE] שגיאה בביצוע טרייד {symbol}: {e}")
        return {"status": "error", "error": str(e)}

