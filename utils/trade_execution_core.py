# utils/trade_execution_core.py
import logging
import asyncio
from typing import Optional, Dict, Any

from utils.ws_fallback import get_price_smart
from utils.sl_tp_utils import calculate_sl_tp
from utils import config

# ננסה להשתמש בטריידר הייעודי אם קיים (מבצע פקודות אמת)
_TRADER_OK = True
try:
    from utils.binance_trader import binance_futures_trade  # type: ignore
except Exception as e:
    _TRADER_OK = False
    logging.info("[trade_core] binance_trader unavailable → will return DRY response: %s", e)

MAX_LEVERAGE = int(getattr(config, "MAX_LEVERAGE", 35))
EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", False))
BINANCE_SKIP_ACCOUNT_MUTATIONS = bool(getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS", True))
MUTATIONS_DISABLED = (not EXECUTE_TRADES) or BINANCE_SKIP_ACCOUNT_MUTATIONS

def _norm_side(side: str) -> str:
    s = (side or "").strip().upper()
    if s in ("LONG", "BUY"):
        return "LONG"
    if s in ("SHORT", "SELL"):
        return "SHORT"
    raise ValueError("side must be LONG/SHORT")

def _safe_lev(x: Optional[int]) -> int:
    try:
        v = int(x or 10)
    except Exception:
        v = 10
    return max(1, min(v, MAX_LEVERAGE))

async def execute_trade_live(
    *,
    symbol: str,
    side: str,                 # LONG / SHORT
    entry: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    budget_usd: float = 100.0,
    leverage: int = 10,
    market_type: str = "futures",
    atr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    זרימת ביצוע:
      1) קבלת מחיר חי (WS→REST fallback) אם entry לא סופק.
      2) חישוב SL/TP אם לא התקבלו, לפי ATR או רצפת אחוזים מ-config.
      3) אם מותר לבצע (EXECUTE_TRADES ו-mut. מותרים) ויש trader – יבצע;
         אחרת DRY-run מפורט (לוגיקה מלאה, ללא כתיבה לחשבון).
    """
    symbol_u = (symbol or "").upper().strip()
    if not symbol_u:
        return {"status": "error", "error": "symbol required"}

    side_u = _norm_side(side)
    lev = _safe_lev(leverage)

    # 1) מחיר חי (אם לא ניתן entry)
    live = entry
    if live is None:
        live = await get_price_smart(symbol_u)
    if live is None or float(live) <= 0:
        return {"status": "error", "error": "live/entry price unavailable", "symbol": symbol_u}

    # 2) SL/TP אם חסרים
    if sl is None or tp is None:
        sl_calc, tp_calc = calculate_sl_tp(entry_price=float(live), direction=side_u, atr=atr)
        sl = float(sl or sl_calc)
        tp = float(tp or tp_calc)

    # הגנות בסיסיות
    if side_u == "LONG" and not (sl < live < tp):
        return {"status": "error", "error": "invalid SL/TP for LONG", "live": float(live), "sl": float(sl), "tp": float(tp)}
    if side_u == "SHORT" and not (tp < live < sl):
        return {"status": "error", "error": "invalid SL/TP for SHORT", "live": float(live), "sl": float(sl), "tp": float(tp)}

    # 3) DRY או ביצוע אמיתי
    plan = {
        "symbol": symbol_u,
        "side": side_u,
        "entry": float(live),
        "sl": float(sl),
        "tp": float(tp),
        "leverage": lev,
        "budget": float(budget_usd),
        "market_type": market_type,
    }

    if MUTATIONS_DISABLED or not _TRADER_OK or market_type.lower() != "futures":
        reasons = []
        if MUTATIONS_DISABLED:
            if not EXECUTE_TRADES:
                reasons.append("EXECUTE_TRADES=false")
            if BINANCE_SKIP_ACCOUNT_MUTATIONS:
                reasons.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
        if not _TRADER_OK:
            reasons.append("binance_trader unavailable")
        if market_type.lower() != "futures":
            reasons.append("this trader supports futures only")
        return {"status": "dry_run", "reason": " & ".join(reasons) or None, "plan": plan}

    try:
        res = await binance_futures_trade(
            symbol=symbol_u,
            side=side_u,
            entry=float(live),
            sl=float(sl),
            tp=float(tp),
            leverage=lev,
            budget=float(budget_usd),
            market_type="futures",
        )
        return {"status": "success", "result": res, "plan": plan}
    except Exception as e:
        logging.error("[trade_core] execution failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "plan": plan}

# שכבת נוחות סינכרונית (למקומות לא-async)
def execute_trade_live_sync(**kwargs) -> Dict[str, Any]:
    return asyncio.run(execute_trade_live(**kwargs))

