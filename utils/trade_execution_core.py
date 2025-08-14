# utils/trade_execution_core.py
from typing import Optional, Dict, Any
from utils.ws_fallback import get_price_smart  # async מחיר חי חכם (WS/REST)

async def execute_trade_live(
    *,
    symbol: str,
    side: str,                 # "LONG" / "SHORT"
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    budget_usd: float = 100.0,
    leverage: int = 10,
    market_type: str = "futures",
) -> Dict[str, Any]:
    """
    ביצוע טרייד (דמו/סימולציה): מחזיר מבנה סטנדרטי עם status.
    במימוש אמיתי תבצע כאן קריאת Binance בפועל.
    """
    try:
        price = float(entry) if entry is not None else await get_price_smart(symbol)
        if price is None or price <= 0:
            return {"status": "error", "error": f"live price unavailable for {symbol}"}

        result = {
            "symbol": str(symbol).upper(),
            "side": str(side).upper(),          # LONG/SHORT
            "entry": float(price),
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "leverage": int(leverage),
            "budget_usd": float(budget_usd),
            "market_type": market_type,
        }
        # כאן אפשר להחליף לסחיבת הזמנה אמיתית מול Binance, ולהחזיר מזהה וכו'.
        return {"status": "success", "result": result}

    except Exception as e:
        return {"status": "error", "error": str(e)}



