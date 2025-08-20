# utils/grid_utils.py
import logging
from utils.ws_fallback import get_price, is_price_fresh

logger = logging.getLogger("algogpt.grid")


def execute_grid_trade(symbol: str, levels: int = 5):
    """
    פונקציית Grid בסיסית: מושכת מחיר עדכני ומריצה חישוב על בסיסו
    """
    price = get_price(symbol)
    if not price:
        logger.error(f"[GRID] No price available for {symbol}")
        return {"ok": False, "error": "No price available"}

    if not is_price_fresh(symbol):
        logger.warning(f"[GRID] Price for {symbol} is stale")
        return {"ok": False, "error": "Price not fresh"}

    # חישוב Grid בסיסי
    step = price * 0.01  # 1% גודל רשת
    levels_data = [round(price + (i - levels // 2) * step, 2) for i in range(levels)]

    logger.info(f"[GRID] {symbol} base={price}, levels={levels_data}")
    return {"ok": True, "symbol": symbol.upper(), "base_price": price, "grid_levels": levels_data}










