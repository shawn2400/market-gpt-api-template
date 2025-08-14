# utils/grid_utils.py
import logging
from typing import Dict, Any, List, Optional, Tuple

from utils import config
from utils.ws_fallback import get_price, is_price_fresh

# ניסיון לייבא כותב ייעודי לגריד (לא חובה; DRY-RUN במקרה שאין)
_BINANCE_GRID_OK = True
try:
    # צפוי: async def binance_grid_trade(symbol, market_type, leverage, levels, total_budget) -> dict
    from utils.binance_trader import binance_grid_trade  # type: ignore
except Exception as _e:
    _BINANCE_GRID_OK = False
    logging.info("[GRID] dedicated binance_grid_trade not available: %s (will DRY-run)", _e)

PRICE_MAX_AGE_SEC = int(getattr(config, "PRICE_MAX_AGE_SEC", 10))

EXECUTE_TRADES = bool(getattr(config, "EXECUTE_TRADES", False))
BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV = str(
    getattr(config, "BINANCE_SKIP_ACCOUNT_MUTATIONS", "true")
).lower() in ("1", "true", "yes", "y", "on")

# אם אחד משני הבלמים פעיל -> אין כתיבה
MUTATIONS_DISABLED = (not EXECUTE_TRADES) or BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV


def _validate_inputs(
    symbol: str,
    budget_usd: float,
    grid_count: int,
    grid_pct: float,
    tp_pct: float,
    sl_pct: float,
    leverage: int,
    futures: bool,
) -> Optional[str]:
    if not symbol or not isinstance(symbol, str):
        return "symbol required"
    if budget_usd <= 0:
        return "budget must be > 0"
    if grid_count < 2:
        return "grid_count must be >= 2"
    if grid_pct <= 0 or tp_pct <= 0 or sl_pct <= 0:
        return "grid_pct/tp_pct/sl_pct must be > 0"
    if futures and leverage <= 0:
        return "leverage must be > 0 for futures"
    return None


def _step_up_down(price: float, pct: float) -> Tuple[float, float]:
    """
    מחזיר (up, down) מהמחיר הנתון באחוז pct (למשל pct=0.4 -> 0.4%)
    """
    f = pct / 100.0
    return price * (1.0 + f), price * (1.0 - f)


def _mk_tp_sl(base: float, side: str, tp_pct: float, sl_pct: float) -> Tuple[float, float]:
    tpm = tp_pct / 100.0
    slm = sl_pct / 100.0
    if side.upper() == "BUY":
        tp = base * (1.0 + tpm)
        sl = base * (1.0 - slm)
    else:  # SELL
        tp = base * (1.0 - tpm)
        sl = base * (1.0 + slm)
    return round(tp, 6), round(sl, 6)


def build_grid_plan(
    *,
    symbol: str,
    live_price: float,
    budget_usd: float,
    grid_count: int,
    grid_pct: float,
    tp_pct: float,
    sl_pct: float,
    futures: bool,
    leverage: int,
) -> Dict[str, Any]:
    """
    בונה תכנית גריד סימטרית סביב המחיר החי:
    חצי רמות מתחת (BUY), חצי מעל (SELL), עם TP/SL לכל רמה.
    """
    price = float(live_price)
    half = grid_count // 2
    tranche = float(budget_usd) / float(grid_count)

    levels: List[Dict[str, Any]] = []

    # מתחת למחיר — קניות
    p_down = price
    for _ in range(half):
        _, p_down = _step_up_down(p_down, grid_pct)  # יורדים צעד
        tp_px, sl_px = _mk_tp_sl(p_down, "BUY", tp_pct, sl_pct)
        levels.append({
            "side": "BUY",
            "price": round(p_down, 6),
            "tp": tp_px,
            "sl": sl_px,
            "budget": round(tranche, 4),
        })

    # מעל המחיר — מכירות
    p_up = price
    for _ in range(grid_count - half):
        p_up, _ = _step_up_down(p_up, grid_pct)  # עולים צעד
        tp_px, sl_px = _mk_tp_sl(p_up, "SELL", tp_pct, sl_pct)
        levels.append({
            "side": "SELL",
            "price": round(p_up, 6),
            "tp": tp_px,
            "sl": sl_px,
            "budget": round(tranche, 4),
        })

    plan = {
        "symbol": symbol.upper().strip(),
        "market_type": "futures" if futures else "spot",
        "leverage": int(leverage) if futures else None,
        "live_price": price,
        "grid_count": int(grid_count),
        "grid_pct": float(grid_pct),
        "tp_pct": float(tp_pct),
        "sl_pct": float(sl_pct),
        "levels": levels,
        "total_budget": float(budget_usd),
    }
    return plan


async def execute_grid_trade(
    *,
    symbol: str,
    budget_usd: float,
    grid_count: int = 6,
    grid_pct: float = 0.4,    # אחוז הפרדה בין רמות
    leverage: int = 20,       # בשימוש ב-futures בלבד
    futures: bool = True,     # True=futures, False=spot
    tp_pct: float = 1.5,      # TP אחוזי לכל רמה
    sl_pct: float = 1.0,      # SL אחוזי לכל רמה
) -> Dict[str, Any]:
    """
    בונה תכנית גריד ומנסה לבצע אותה (אם מותר).
    אם כתיבה מושבתת/אין writer — מוחזר DRY plan.
    """
    try:
        # ולידציות בסיסיות
        err = _validate_inputs(symbol, budget_usd, grid_count, grid_pct, tp_pct, sl_pct, leverage, futures)
        if err:
            return {"status": "error", "error": err}

        # מחיר חי ועדכני
        live = await get_price(symbol)
        if live is None or not is_price_fresh(symbol, max_age_sec=PRICE_MAX_AGE_SEC):
            return {"status": "error", "error": "live price unavailable or stale"}

        # בניית תוכנית
        plan = build_grid_plan(
            symbol=symbol,
            live_price=float(live),
            budget_usd=budget_usd,
            grid_count=grid_count,
            grid_pct=grid_pct,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            futures=futures,
            leverage=leverage,
        )

        # DRY-RUN אם כתיבה מושבתת או אין writer ייעודי
        if MUTATIONS_DISABLED or not _BINANCE_GRID_OK:
            reasons = []
            if MUTATIONS_DISABLED:
                if not EXECUTE_TRADES:
                    reasons.append("EXECUTE_TRADES=false")
                if BINANCE_SKIP_ACCOUNT_MUTATIONS_ENV:
                    reasons.append("BINANCE_SKIP_ACCOUNT_MUTATIONS=true")
            if not _BINANCE_GRID_OK:
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








