# utils/trade_execution_core.py
from typing import Optional, Dict, Any
from utils.ws_fallback import get_price_smart  # אסינכרוני

async def execute_trade_live(
    *,
    symbol: str,
    side: str,
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    budget_usd: float = 100.0,
    leverage: int = 10,
    market_type: str = "futures",
) -> Dict[str, Any]:
    """
    DRY-RUN מבוקר: לא שולח הזמנה אמיתית, רק מחזיר פרטי 'ביצוע' לצורך בדיקות/לוגים.
    אם entry=None, מביאים מחיר חי דרך get_price_smart.
    """
    live = await get_price_smart(symbol)
    price = float(entry) if entry is not None else float(live or 0.0)
    if price <= 0:
        return {"status": "error", "error": f"live price unavailable for {symbol}"}

    result = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "entry": price,
        "sl": float(sl) if sl is not None else None,
        "tp": float(tp) if tp is not None else None,
        "leverage": int(leverage),
        "budget_usd": float(budget_usd),
        "market_type": market_type,
    }
    # בעתיד: אם EXECUTE_TRADES=True ונתיב כתיבה קיים — לקרוא ל-writer אמיתי כאן.
    return {"status": "success", "result": result}




