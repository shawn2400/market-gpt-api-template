# utils/grid_executor.py
import logging
from typing import Dict, Any, List, Optional

from utils import config
from utils.ws_fallback import get_price, is_price_fresh

# נסיונות ייבוא — נתיבי כתיבה לגריד (אם קיים מימוש ייעודי)
_grid_route_ok = True
try:
    from utils.binance_trader import binance_grid_trade  # async, אופציונלי
except Exception as _e:
    _grid_route_ok = False
    logging.info("[GRID] dedicated binance_grid_trade not available: %s (will return DRY plan)", _e)

PRICE_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))
EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", False))
BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV = str(
    getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS", "true")
).lower() in ("1", "true", "yes", "y", "on")
MUTATIONS_DISABLED = (not EXECUTE_TRADES) or BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV


async def execute_grid_trade(
    *,
    symbol: str,
    budget_usd: float,
    grid_count: int = 6,
    grid_pct: float = 0.4,     # מרחק בין רמות (באחוזים, למשל 0.4% בין רשתות)
    leverage: int = 20,        # בשימוש ב-futures בלבד
    futures: bool = True,      # True=futures, False=spot
    tp_pct: float = 1.5,       # Take-profit יחסי לכל רשת (באחוזים)
    sl_pct: float = 1.0,       # Stop-loss יחסי לכל רשת (באחוזים)
) -> Dict[str, Any]:
    """
    בונה/מבצע גריד פשוט סביב המחיר הנוכחי:
    - grid_count רמות קנייה/מכירה מפוזרות ב-%grid_pct לכל קפיצה
    - לכל רמה מוגדר TP/SL יחסיים (באחוזים)
    - אם הוגדר futures: משתמשים ב-leverage לצורך חישוב כמות (בצד הwriter)
    - אם כתיבה מושבתת: מוחזר DRY plan מפורט
    """
    try:
        symbol = str(symbol).upper().strip()
        if budget_usd <= 0:
            return {"status": "error", "error": "budget_usd must be > 0"}
        if grid_count < 2:
            return {"status": "error", "error": "grid_count must be >= 2"}
        if grid_pct <= 0 or tp_pct <= 0 or sl_pct <= 0:
            return {"status": "error", "error": "grid_pct/tp_pct/sl_pct must be > 0"}

        # מחיר חי
        live = await get_price(symbol)
        if live is None or not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            return {"status": "error", "error": "live price unavailable or stale"}

        # בנה רמות — חצי מתחת למחיר, חצי מעל (עגול כלפי מטה/מעלה לפי סדר)
        half = grid_count // 2
        levels: List[Dict[str, float]] = []

        def _ppct(p, pct):
            # pct באחוזים (למשל 0.4) => מכפיל 0.004
            f = pct / 100.0
            return p * (1.0 + f), p * (1.0 - f)

        # רמות מתחת (קנייה/Long), ואחר כך מעל (מכירה/Short)
        price = float(live)
        step_pct = float(grid_pct)

        # למטה
        p_down = price
        for _ in range(half):
            _, p_down = _ppct(p_down, step_pct)  # הורד באחוז מוגדר
            levels.append({"side": "BUY", "price": p_down})

        # למעלה
        p_up = price
        for _ in range(grid_count - half):
            p_up, _ = _ppct(p_up, step_pct)  # העלה באחוז מוגדר
            levels.append({"side": "SELL", "price": p_up})

        # TP/SL לכל רמה (באחוזים יחסית למחיר הרמה)
        def _mk_tp_sl(base: float, side: str) -> (float, float):
            tp_mul = tp_pct / 100.0
            sl_mul = sl_pct / 100.0
            if side == "BUY":
                tp = base * (1.0 + tp_mul)
                sl = base * (1.0 - sl_mul)
            else:  # SELL
                tp = base * (1.0 - tp_mul)
                sl = base * (1.0 + sl_mul)
            return round(tp, 6), round(sl, 6)

        plan_levels: List[Dict[str, Any]] = []
        tranche = float(budget_usd) / float(grid_count)

        for lv in levels:
            side = lv["side"]
            lvl_price = float(lv["price"])
            tp_px, sl_px = _mk_tp_sl(lvl_price, side)
            plan_levels.append({
                "side": side,
                "price": round(lvl_price, 6),
                "tp": tp_px,
                "sl": sl_px,
                "budget": round(tranche, 4),
            })

        plan = {
            "symbol": symbol,
            "market_type": "futures" if futures else "spot",
            "leverage": int(leverage) if futures else None,
            "live_price": price,
            "grid_count": grid_count,
            "grid_pct": grid_pct,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "levels": plan_levels,
            "total_budget": float(budget_usd),
        }

        # DRY-RUN אם כתיבה מושבתת או אין נתיב ייעודי
        if MUTATIONS_DISABLED or not _grid_route_ok:
            reason = []
            if MUTATIONS_DISABLED:
                if not EXECUTE_TRADES:
                    reason.append("EXECUTE_TRADES=false")
                if BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV:
                    reason.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
            if not _grid_route_ok:
                reason.append("binance_grid_trade unavailable")
            return {"status": "dry_run", "reason": " & ".join(reason), "plan": plan}

        # ביצוע בפועל דרך writer ייעודי (מומלץ ליעל בצד הכתיבה)
        result = await binance_grid_trade(
            symbol=symbol,
            market_type=plan["market_type"],
            leverage=plan["leverage"],
            levels=plan_levels,
            total_budget=budget_usd
        )
        return {"status": "success", "result": result, "plan": plan}

    except Exception as e:
        logging.error("[GRID] exception executing grid for %s: %s", symbol, e, exc_info=True)
        return {"status": "error", "error": str(e)}
