# utils/trade_execution_core.py
from utils.ws_fallback import get_price

def execute_trade_live(symbol, side, entry=None, sl=None, tp=None, budget_usd=100, leverage=10, market_type="futures"):
    """
    ביצוע טרייד לייב (פשטני/דמו): מביא מחיר (אם לא נשלח), ומחזיר תוצאה עם status.
    במימוש אמיתי – שגר הזמנה ל-Binance והחזר מזהה/פרטים.
    """
    try:
        price = float(entry) if entry is not None else get_price(symbol)
        if price is None:
            return {"status": "error", "error": f"live price unavailable for {symbol}"}

        # כאן היית מבצע את הקריאה לאקסצ'יינג' בפועל. כרגע: סימולציה/לוג בלבד.
        result = {
            "symbol": str(symbol).upper(),
            "side": str(side).upper(),          # LONG/SHORT
            "entry": price,
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "leverage": int(leverage),
            "budget_usd": float(budget_usd),
            "market_type": market_type,
        }
        # החזרה סטנדרטית כדי ש-/trade יחזיר success
        return {"status": "success", "result": result}

    except Exception as e:
        return {"status": "error", "error": str(e)}


