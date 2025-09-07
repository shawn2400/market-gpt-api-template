# utils/trade_manager.py
from __future__ import annotations
import logging, asyncio
from typing import Any, Dict, List

from utils import ws_fallback
from utils.indicators import atr, macd, adx
from utils.binance_client import (
    modify_stop_loss,
    modify_take_profit,
    get_open_positions,
    get_klines_df,
)
from utils.config import ALLOW_MANAGE_OPEN_TRADES, _as_float

logger = logging.getLogger("algogpt.trade_manager")

# שליטה דרך ENV
BE_ARM_PCT = _as_float("BE_ARM_PCT", 1.6)          # אחוז רווח להזזת SL ל־BE
TRAIL_ATR_MULT = _as_float("TRAIL_ATR_MULT", 1.5)  # מקדם ל־ATR ב־Trailing


async def manage_open_trades() -> List[Dict[str, Any]]:
    """
    מנהל פוזיציות פתוחות:
    - SL ל־Breakeven אחרי TP1
    - Trailing SL לפי ATR
    - עדכון TP לפי מומנטום
    """
    results: List[Dict[str, Any]] = []

    if not ALLOW_MANAGE_OPEN_TRADES:
        logger.info("[manage] ❌ ALLOW_MANAGE_OPEN_TRADES is False – skipping")
        return results

    logger.info("[manage] ✨ Starting management of open trades...")
    try:
        positions = get_open_positions()
        for pos in positions:
            sym = pos.get("symbol")
            qty = float(pos.get("positionAmt") or 0)
            entry = float(pos.get("entryPrice") or 0)
            side = "LONG" if qty > 0 else "SHORT"

            price = ws_fallback.get_price(sym) or float(pos.get("markPrice") or 0)
            if price <= 0 or entry <= 0 or abs(qty) <= 0:
                continue

            df = get_klines_df(sym, interval="5m", limit=50)
            if df is None or df.empty:
                continue

            # === אינדיקטורים
            current_atr = atr(df)[-1]
            current_adx = adx(df)[-1]
            macd_line, macd_signal, _ = macd(df["close"])
            macd_now = macd_line.iloc[-1] - macd_signal.iloc[-1]

            profit_pct = abs((price - entry) / entry) * 100

            updates: Dict[str, Any] = {"symbol": sym, "side": side, "price": price}

            # === Breakeven SL ===
            if profit_pct >= BE_ARM_PCT and (macd_now > 0 or current_adx > 20):
                new_sl = entry
                logger.info(f"[manage][{sym}] Moving SL → BE: {new_sl}")
                resp = modify_stop_loss(sym, side, new_sl, abs(qty))
                updates["breakeven_sl"] = resp

            # === Trailing SL ===
            trail_sl = None
            if side == "LONG":
                recent_low = df["low"].iloc[-3:].min()
                trail_sl = recent_low - 0.6 * current_atr
            else:
                recent_high = df["high"].iloc[-3:].max()
                trail_sl = recent_high + 0.6 * current_atr

            if trail_sl:
                logger.info(f"[manage][{sym}] Trailing SL → {trail_sl}")
                resp = modify_stop_loss(sym, side, trail_sl, abs(qty))
                updates["trailing_sl"] = resp

            # === Dynamic TP ===
            if current_adx > 25 and macd_now > 0:
                if side == "LONG":
                    new_tp = price + 4.5 * current_atr
                else:
                    new_tp = price - 4.5 * current_atr
                logger.info(f"[manage][{sym}] Momentum TP → {new_tp}")
                resp = modify_take_profit(sym, side, new_tp, abs(qty))
                updates["momentum_tp"] = resp

            results.append(updates)

        return results

    except Exception as e:
        logger.error(f"[manage] Error during trade management: {e}")
        return results



