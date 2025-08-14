# utils/trade_execution_core.py
import logging
from typing import Optional, Dict, Any
from utils.ws_fallback import get_price as _get_price

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
    ביצוע טרייד "לוגי" אחיד (תואם חתימה של main.py):
    - מביא live price אם entry=None
    - מחזיר אובייקט תוצאה סטנדרטי; בפועל אינו משגר הזמנה אמיתית כאן.
    """
    try:
        side = (side or "").upper().strip()
        if side not in ("LONG", "SHORT", "BUY", "SELL"):
            return {"status": "error", "error": f"invalid side: {side}"}
        # Normalize
        side = "LONG" if side in ("LONG", "BUY") else "SHORT"

        price = float(entry) if entry is not None else None
        if price is None:
            price = await _get_price(symbol)
        if price is None or float(price) <= 0:
            return {"status": "error", "error": f"live price unavailable for {symbol}"}

        result = {
            "symbol": str(symbol).upper(),
            "side": side,
            "entry": float(price),
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "leverage": int(leverage),
            "budget_usd": float(budget_usd),
            "market_type": market_type,
        }
        logging.info(
            "⏺️ EXECUTE (DRY): %s %s @ %.6f | lev=%s | budget=%s | sl=%s | tp=%s | market=%s",
            result["side"], result["symbol"], result["entry"], result["leverage"],
            result["budget_usd"], result["sl"], result["tp"], result["market_type"]
        )
        # כאן אפשר לשלב כתיבה אמיתית לבינאנס אם תרצה
        return {"status": "success", "result": result}
    except Exception as e:
        logging.error("[trade_execution_core] %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


