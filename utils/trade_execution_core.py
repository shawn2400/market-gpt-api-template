# utils/trade_execution_core.py
import logging
from typing import Optional, Dict, Any

from utils.ws_fallback import get_price_smart

# אפשרות להפעיל "ביצוע אמיתי" בעתיד דרך קונפיג/ENV
import os
EXECUTE_REAL = str(os.getenv("ALGOGPT_EXECUTE_REAL", "false")).lower() in ("1", "true", "yes")

def _estimate_qty(symbol: str, price: float, budget_usd: float, leverage: int) -> float:
    """
    חישוב כמות מקורב: notional = budget * leverage
    qty = notional / price
    לא מבצע התאמה ל-step-size (כי DRY-RUN) אבל מעגל יפה.
    """
    if price <= 0:
        return 0.0
    notional = float(budget_usd) * int(leverage)
    qty = notional / price
    # עיגול סביר: BTC/ETH ל-0.001, אלטים ל-0.1
    if symbol.upper().startswith(("BTC", "ETH")):
        return round(qty, 3)
    return round(qty, 1)

async def execute_trade_live(
    symbol: str,
    side: str,
    entry: Optional[float],
    sl: float,
    tp: float,
    leverage: int,
    budget_usd: float,
    market_type: str = "futures",
) -> Dict[str, Any]:
    """
    ביצוע טרייד "לוגי". כברירת מחדל DRY-RUN: מחזיר תוצאה סימולטיבית.
    אם EXECUTE_REAL=True (ENV), כאן המקום לחבר להזמנות אמיתיות.
    """
    try:
        symbol_u = symbol.upper()
        side_u = side.upper()

        # מחיר כניסה (אם לא סופק — מביאים חי)
        if entry is None:
            live = await get_price_smart(symbol_u)
            if live is None or float(live) <= 0:
                return {"status": "error", "error": "live price unavailable"}
            entry_price = float(live)
        else:
            entry_price = float(entry)

        if sl is None or tp is None:
            return {"status": "error", "error": "SL/TP required"}

        qty = _estimate_qty(symbol_u, entry_price, float(budget_usd), int(leverage))

        plan = {
            "symbol": symbol_u,
            "side": side_u,                 # LONG/SHORT
            "entry": round(entry_price, 2),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget_usd": float(budget_usd),
            "market_type": market_type,
            "qty": qty,
            "mode": "DRY-RUN" if not EXECUTE_REAL else "LIVE",
        }

        # כאן אפשר להכניס ביצוע אמיתי בעתיד (EXECUTE_REAL=True)
        if EXECUTE_REAL:
            # לדוגמה בלבד (לא ממומש בכוונה):
            # client = get_client()
            # order = client.futures_create_order(...)
            # plan["exchange_order_id"] = order.get("orderId")
            logging.info("[trade] LIVE not implemented; returning DRY-RUN plan")
            pass

        logging.info("[trade] plan: %s", plan)
        return {"status": "success", "result": plan}

    except Exception as e:
        logging.error("[trade] execute error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}






