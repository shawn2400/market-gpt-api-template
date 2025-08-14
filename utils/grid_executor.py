# utils/grid_executor.py
import logging
from typing import Dict, Any, List

from utils import config
from utils.ws_fallback import get_price, is_price_fresh

# נסיון ייבוא נתיב כתיבה לגריד (אופציונלי)
_GRID_WRITER_OK = True
try:
    # צפוי: async def binance_grid_trade(symbol, market_type, leverage, levels, total_budget) -> dict
    from utils.binance_trader import binance_grid_trade  # type: ignore
except Exception as _e:
    _GRID_WRITER_OK = False
    logging.info("[GRID] dedicated binance_grid_trade not available: %s (will DRY-run)", _e)

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
    grid_pct: float = 0.4,     # אחוז קפיצה בין רמות (0.4 => 0.4%)
    leverage: int = 20,        # בשימוש ב-futures בלבד
    futures: bool = True,      # True=futures, False=spot
    tp_pct: float = 1.5,       # TP יחסי לכל רמה, באחוזים
    sl_pct: float = 1.0,       # SL יחסי לכל רמה, באחוזים
) -> Dict[str, Any]:
    """
    בונה תכנית גריד סימטרית סביב המחיר הנוכחי ומבצע אותה אם אפשר.
    אחרת — DRY plan מפורט.
    """
    try:
        symbol = str(symbol or "").upper().strip()
        if not symbol:
            return {"status": "error", "error": "symbol required"}
        if budget_usd <= 0:
            return {"status": "error", "error": "budget_usd must be > 0"}
        if grid_count < 2:
            return {"status": "error", "error": "grid_count must be >= 2"}
        if min(grid_pct, tp_pct, sl_pct) <= 0:
            return {"status": "error", "error": "grid_pct/tp_pct/sl_pct must be > 0"}

        live = await get_price(symbol)
        if live is None or not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            return {"status": "error", "error": "live price unavailable or stale"}

        price = float(live)
        half = grid_count // 2

        def _step_up_down(p: float, pct: float) -> tuple[float, float]:
            f = pct / 100.0
            return p * (1.0 + f), p * (1.0 - f)

        # רמות: חצי BUY מתחת, חצי SELL מעל
        levels_raw: List[Dict[str, float]] = []
        p_down = price
        for _ in range(half):
            _, p_down = _step_up_down(p_down, grid_pct)
            levels_raw.append({"side": "BUY", "price": p_down})

        p_up = price
        for _ in range(grid_count - half):
            p_up, _ = _step_up_down(p_up, grid_pct)
            levels_raw.append({"side": "SELL", "price": p_up})

        def _mk_tp_sl(base: float, side: str) -> tuple[float, float]:
            tpm = tp_pct / 100.0
            slm = sl_pct / 100.0
            if side == "BUY":
                tp = base * (1.0 + tpm)
                sl = base * (1.0 - slm)
            else:
                tp = base * (1.0 - tpm)
                sl = base * (1.0 + slm)
            return round(tp, 6), round(sl, 6)

        tranche = float(budget_usd) / float(grid_count)
        plan_levels: List[Dict[str, Any]] = []
        for lv in levels_raw:
            tp_px, sl_px = _mk_tp_sl(float(lv["price"]), lv["side"])
            plan_levels.append({
                "side": lv["side"],
                "price": round(float(lv["price"]), 6),
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
            "grid_pct": float(grid_pct),
            "tp_pct": float(tp_pct),
            "sl_pct": float(sl_pct),
            "levels": plan_levels,
            "total_budget": float(budget_usd),
        }

        if MUTATIONS_DISABLED or not _GRID_WRITER_OK:
            reasons = []
            if MUTATIONS_DISABLED:
                if not EXECUTE_TRADES:
                    reasons.append("EXECUTE_TRADES=false")
                if BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV:
                    reasons.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
            if not _GRID_WRITER_OK:
                reasons.append("binance_grid_trade unavailable")
            return {"status": "dry_run", "reason": " & ".join(reasons), "plan": plan}

        # ביצוע בפועל
        result = await binance_grid_trade(
            symbol=plan["symbol"],
            market_type=plan["market_type"],
            leverage=plan["leverage"],
            levels=plan["levels"],
            total_budget=plan["total_budget"],
        )
        return {"status": "success", "result": result, "plan": plan}

    except Exception as e:
        logging.error("[GRID] exception executing grid for %s: %s", symbol, e, exc_info=True)
        return {"status": "error", "error": str(e)}

