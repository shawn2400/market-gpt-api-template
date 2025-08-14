# utils/trade_execution_core.py
import logging
from typing import Optional, Dict, Any

from utils import config
from utils.ws_fallback import get_price_smart, is_price_fresh

# פקדי כתיבה:
EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", True))
BINANCE_SKIP_ACCOUNT_MUTATIONS = str(
    getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS", "false")
).strip().lower() in ("1", "true", "yes", "y", "on")

MUTATIONS_DISABLED = (not EXECUTE_TRADES) or BINANCE_SKIP_ACCOUNT_MUTATIONS

async def execute_trade_live(
    *,
    symbol: str,
    side: str,           # LONG / SHORT
    entry: Optional[float],
    sl: float,
    tp: float,
    leverage: int,
    budget_usd: float,
    market_type: str = "futures",
) -> Dict[str, Any]:
    """
    שכבה אחידה לביצוע טרייד. כרגע DRY-RUN/אקו מתוכנן; חיבור אמיתי ניתן להוסיף כאן מאוחר יותר.
    מחזיר תמיד מבנה עקבי כדי שה-API יישאר יציב.
    """
    try:
        sy = str(symbol).upper().strip()
        sd = str(side).upper().strip()
        if sd not in ("LONG", "SHORT"):
            return {"status": "error", "error": "side must be LONG/SHORT"}

        px = entry
        if px is None or float(px) <= 0:
            live = await get_price_smart(sy)
            if live is None:
                return {"status": "error", "error": "live price unavailable"}
            px = float(live)

        # ודא שיש מחיר עדכני (אם ידוע)
        if not is_price_fresh(sy, max_age_sec=int(getattr(config, "PRICE_MAX_AGE_SEC", 10))):
            logging.warning("[trade] price for %s may be stale", sy)

        result_payload = {
            "symbol": sy,
            "side": sd,
            "entry": float(px),
            "sl": float(sl),
            "tp": float(tp),
            "leverage": int(leverage),
            "budget_usd": float(budget_usd),
            "market_type": str(market_type),
        }

        # כרגע — DRY-RUN/אקו (ללא כתיבה לחשבון). אפשר להרחיב כאן בהמשך.
        if MUTATIONS_DISABLED:
            reason = []
            if not EXECUTE_TRADES:
                reason.append("EXECUTE_TRADES=false")
            if BINANCE_SKIP_ACCOUNT_MUTATIONS:
                reason.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
            return {
                "status": "success",
                "mode": "dry_run",
                "reason": " & ".join(reason) if reason else "mutations disabled",
                "result": result_payload,
            }

        # אם תרצה לבצע הזמנה אמיתית – זה המקום להוסיף חיבור ל-python-binance.
        # כרגע נחזיר אקו "success" כדי לשמור על יציבות הממשק.
        return {
            "status": "success",
            "mode": "execute",
            "result": result_payload,
        }

    except Exception as e:
        logging.error("[trade_execution_core] error: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}





