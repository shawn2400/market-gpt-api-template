# utils/grid_executor.py
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from utils.ws_fallback import get_price, is_price_fresh
from utils.precision_utils import apply_price_tick_side, calc_quantity_from_budget
from utils.binance_client import place_limit_order, set_leverage
from utils.grid_planner import plan_grid
from utils.grid_tracker import add_grid

logger = logging.getLogger("algogpt.grid.executor")


async def execute_grid_trade(
    *,
    symbol: str,
    side: str,
    budget: float,
    leverage: int = 10,
    grids: int = 3,
    atr_mults: Optional[List[float]] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    מבצע Grid Trade (Futures בלבד).
    - side: LONG/SHORT
    - budget: תקציב כולל ב-USDT
    - leverage: מינוף
    - grids: מספר רמות
    - atr_mults: לא חובה, ברירת מחדל [1.0, 1.8, 2.6]
    """

    s = symbol.upper().strip()
    side_u = side.upper().strip()
    atr_mults = atr_mults or [1.0, 1.8, 2.6]

    # --- בדיקת מחיר חי ---
    price = get_price(s)
    if not price or not is_price_fresh(s):
        return {"ok": False, "error": f"Price not available/fresh for {s}"}

    # --- תכנון Grid ---
    plan = plan_grid(symbol=s, price=price, flags={"vol_regime": "mid"}, budget_usd=budget, side=side_u)
    if not plan:
        return {"ok": False, "error": f"Grid plan not available for {s}"}

    lines = plan["lines"]
    allocations = plan["allocations_usd"]

    logger.info({
        "event": "grid_plan_ready",
        "symbol": s,
        "side": side_u,
        "levels": lines,
        "allocations": allocations,
    })

    # --- DRY RUN ---
    if dry_run:
        return {
            "mode": "grid_dry_run",
            "ok": True,
            "symbol": s,
            "side": side_u,
            "base_price": float(price),
            "levels": [round(x, 4) for x in lines],
            "allocations": allocations,
            "budget": budget,
            "leverage": leverage,
            "note": "dry_run only, no orders placed",
        }

    # --- LIVE (Futures בלבד) ---
    try:
        set_leverage(s, int(leverage))
    except Exception as e:
        logger.warning(f"[GRID] set_leverage failed for {s}: {e}")

    placed_orders: List[Dict[str, Any]] = []
    for lvl, alloc in zip(lines, allocations):
        if alloc <= 0:
            continue
        qty_info = calc_quantity_from_budget(s, price=lvl, budget_usd=alloc, leverage=leverage)
        if not qty_info.get("ok"):
            logger.warning(f"[GRID] Skipping level {lvl} - qty calc failed: {qty_info}")
            continue
        qty = float(qty_info["qty"])
        px_aligned, _ = apply_price_tick_side(lvl, s, "BUY" if side_u == "LONG" else "SELL")

        try:
            order = place_limit_order(
                symbol=s,
                side="BUY" if side_u == "LONG" else "SELL",
                quantity=qty,
                price=px_aligned,
                time_in_force="GTC",
                post_only=True,
                reduce_only=False,
            )
            placed_orders.append(order)
        except Exception as e:
            logger.error(f"[GRID] Failed to place order at {lvl}: {e}")

    # --- שמירת גריד ---
    grid_data = {
        "symbol": s,
        "side": side_u,
        "levels": [round(x, 4) for x in lines],
        "allocations": allocations,
        "budget": budget,
        "leverage": leverage,
        "orders": placed_orders,
    }
    try:
        add_grid(grid_data)
    except Exception:
        pass

    return {
        "mode": "grid_live",
        "ok": True if placed_orders else False,
        "symbol": s,
        "side": side_u,
        "base_price": float(price),
        "levels": [round(x, 4) for x in lines],
        "budget": budget,
        "leverage": leverage,
        "orders": placed_orders,
    }
