# utils/trade_manager.py
import time, logging, asyncio
from utils import ws_fallback
from utils.indicators import atr, macd, adx
from utils.binance_client import modify_stop_loss, modify_take_profit, get_open_positions, get_klines_df
from utils.config import ALLOW_MANAGE_OPEN_TRADES
from utils.telegram_notifier import notify_sl_tp_update

logger = logging.getLogger("algogpt.trade_manager")

# cooldown של עדכון (שניות)
_COOLDOWN = 30
_last_update: dict[str, float] = {}

async def manage_open_trades():
    if not ALLOW_MANAGE_OPEN_TRADES:
        logger.info("[manage] ❌ ALLOW_MANAGE_OPEN_TRADES is False – skipping")
        return

    logger.info("[manage] ✨ Managing open trades...")
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

            # Cooldown check
            now = time.time()
            if now - _last_update.get(sym, 0) < _COOLDOWN:
                continue

            df = get_klines_df(sym, interval="5m", limit=50)
            if df is None or df.empty:
                continue

            current_atr = atr(df)[-1]
            current_adx = adx(df)[-1]
            macd_line, macd_signal, _ = macd(df["close"])
            macd_now = macd_line.iloc[-1] - macd_signal.iloc[-1]

            profit_pct = abs((price - entry) / entry) * 100

            # === Breakeven SL ===
            if profit_pct >= 1.5 and (macd_now > 0 or current_adx > 20):
                new_sl = entry
                logger.info(f"[manage][{sym}] Moving SL → BE: {new_sl}")
                modify_stop_loss(sym, side, new_sl, abs(qty))
                await notify_sl_tp_update(sym, side, "breakeven", new_sl)

            # === Trailing SL ===
            if side == "LONG":
                recent_low = df["low"].iloc[-3:].min()
                trail_sl = recent_low - 0.6 * current_atr
            else:
                recent_high = df["high"].iloc[-3:].max()
                trail_sl = recent_high + 0.6 * current_atr
            logger.info(f"[manage][{sym}] Trailing SL → {trail_sl}")
            modify_stop_loss(sym, side, trail_sl, abs(qty))
            await notify_sl_tp_update(sym, side, "trailing", trail_sl)

            # === Dynamic TP ===
            if current_adx > 25 and macd_now > 0:
                if side == "LONG":
                    new_tp = price + 4.5 * current_atr
                else:
                    new_tp = price - 4.5 * current_atr
                logger.info(f"[manage][{sym}] Momentum TP → {new_tp}")
                modify_take_profit(sym, side, new_tp, abs(qty))
                await notify_sl_tp_update(sym, side, "tp", new_tp)

            _last_update[sym] = now

    except Exception as e:
        logger.error(f"[manage] Error: {e}")

async def manage_open_trades_loop(interval: int = 20):
    while True:
        await manage_open_trades()
        await asyncio.sleep(interval)




