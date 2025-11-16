# utils/grid_executor.py
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from utils.ws_fallback import get_price, is_price_fresh
from utils.precision_utils import apply_price_tick_side, calc_quantity_from_budget
from utils.binance_client import place_limit_order, set_leverage, futures_create_order
from utils.grid_planner import plan_grid
from utils.grid_tracker import add_grid
from utils.grid_manager import start_grid_for_position  # להצמדת SL/TP אחרי כניסה
from utils.order_router import get_order_router
from utils.sltp import calc_sl_tp_for_symbol  # 🎯 SL/TP calculator
from utils.order_ids import build_client_order_id  # 🎯 Unique client order IDs
from utils.universal_sltp_manager import save_order_metadata  # 🎯 Universal metadata storage

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

    # 📍 Get ATR for Smart Router (assume 2% if unavailable)
    try:
        from utils.get_klines import get_klines
        from utils.indicators import atr as calc_atr
        klines = await get_klines(s, interval="15m", limit=20)
        if klines is not None and len(klines) >= 14:
            import pandas as pd
            df = pd.DataFrame(klines)
            atr_series = calc_atr(df, period=14)
            if not atr_series.empty:
                atr_value = float(atr_series.iloc[-1])
                atr_pct = atr_value / float(price)
            else:
                atr_pct = 0.02
        else:
            atr_pct = 0.02
    except Exception:
        atr_pct = 0.02  # Fallback
    
    placed_orders: List[Dict[str, Any]] = []
    router = get_order_router()
    
    for idx, (lvl, alloc) in enumerate(zip(lines, allocations)):
        if alloc <= 0:
            continue
        qty_info = calc_quantity_from_budget(s, price=lvl, budget_usd=alloc, leverage=leverage)
        if not qty_info.get("ok"):
            logger.warning(f"[GRID] Skipping level {lvl} - qty calc failed: {qty_info}")
            continue
        qty = float(qty_info["qty"])
        px_aligned, _ = apply_price_tick_side(lvl, s, "BUY" if side_u == "LONG" else "SELL")
        
        # 🎯 MANDATORY SL/TP Calculation (per user spec: 5-10% SL, 15-25% TP)
        sl_price, tp_price = calc_sl_tp_for_symbol(
            symbol=s,
            entry=px_aligned,
            side=side_u,
            sl=0.08,  # 8% Stop Loss (middle of 5-10% range)
            tp=0.20,  # 20% Take Profit (middle of 15-25% range)
            atr=None  # Using percentage-based SL/TP as per spec
        )
        
        if not sl_price or not tp_price:
            logger.error(f"[GRID] ❌ SL/TP calculation failed for {s} at {px_aligned} - ABORTING ORDER (no unprotected positions allowed)")
            continue
        
        # 🎯 Generate clientOrderId BEFORE placing order (this is the key!)
        order_side = "BUY" if side_u == "LONG" else "SELL"
        client_order_id = build_client_order_id(s, order_side, role="GRID", extra=f"L{idx}")
        
        # 💾 Save metadata BEFORE order placement (using clientOrderId)
        metadata_saved = save_order_metadata(
            client_order_id=client_order_id,
            symbol=s,
            side=side_u,
            entry_price=px_aligned,
            sl_price=sl_price,
            tp_price=tp_price,
            quantity=qty,
            leverage=leverage,
            trade_type="GRID"
        )
        
        if not metadata_saved:
            logger.warning(f"[GRID] ⚠️ Metadata save failed for {s} level {idx} - order will NOT have SL/TP protection!")
        
        # 📍 Smart Router Decision
        decision = router.route_order(
            atr_pct=atr_pct,
            purpose="GRID",
            urgency="low",  # GRID orders are patient
            is_breakout=False
        )
        order_type = decision["order_type"]

        try:
            if order_type == "LIMIT":
                # Use LIMIT with post-only for sniper precision
                order = place_limit_order(
                    symbol=s,
                    side=order_side,
                    quantity=qty,
                    price=px_aligned,
                    time_in_force="GTC",
                    post_only=True,
                    reduce_only=False,
                    newClientOrderId=client_order_id  # 🎯 Critical: use our clientOrderId
                )
            else:  # MARKET (rare for GRID, but possible in high volatility)
                order = futures_create_order(
                    symbol=s,
                    side=order_side,
                    type="MARKET",
                    quantity=qty,
                    reduceOnly=False,
                    newClientOrderId=client_order_id  # 🎯 Critical: use our clientOrderId
                )
            
            logger.info(f"[GRID] ✅ {order_type} order placed at {px_aligned} | SL={sl_price:.6f} TP={tp_price:.6f} | clientOrderId={client_order_id}")
            placed_orders.append(order)
        except Exception as e:
            logger.error(f"[GRID] Failed to place {order_type} order at {lvl}: {e}")

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

    # --- הצמדת SL/TP חכמה לגריד ---
    try:
        res_mgr = await start_grid_for_position(s, use_indicators=True)
    except Exception as e:
        res_mgr = {"ok": False, "error": f"grid_manager_failed:{e}"}

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
        "manager": res_mgr,
    }

