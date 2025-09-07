# utils/trade_manager.py
import time, logging, asyncio, json
from pathlib import Path
from utils import ws_fallback
from utils.indicators import atr, macd, adx
from utils.binance_client import (
    modify_stop_loss, modify_take_profit,
    get_open_positions, get_klines_df, close_all_positions
)
from utils.config import ALLOW_MANAGE_OPEN_TRADES
from utils.telegram_notifier import (
    notify_sl_tp_update, notify_info,
    notify_error, notify_heartbeat,
    notify_daily_summary, notify_trade_review
)

logger = logging.getLogger("algogpt.trade_manager")

_COOLDOWN = 30
_last_update: dict[str, float] = {}
DAILY_LOSS_CAP = -150.0  # USDT
_symbol_losses: dict[str, float] = {}
_daily_pnl = 0.0
_trades_today: list[dict] = []

REVIEW_PATH = Path("static/cache/trade_reviews.json")

async def manage_open_trades():
    """ניהול דינמי חי של טריידים פתוחים (SL, TP, BE, Trailing)."""
    global _daily_pnl
    if not ALLOW_MANAGE_OPEN_TRADES:
        return

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
                modify_stop_loss(sym, side, new_sl, abs(qty))
                await notify_sl_tp_update(sym, side, "breakeven", new_sl)

            # === Trailing SL ===
            if side == "LONG":
                recent_low = df["low"].iloc[-3:].min()
                trail_sl = recent_low - 0.6 * current_atr
            else:
                recent_high = df["high"].iloc[-3:].max()
                trail_sl = recent_high + 0.6 * current_atr
            modify_stop_loss(sym, side, trail_sl, abs(qty))
            await notify_sl_tp_update(sym, side, "trailing", trail_sl)

            # === Dynamic TP ===
            if current_adx > 25 and macd_now > 0:
                if side == "LONG":
                    new_tp = price + 4.5 * current_atr
                else:
                    new_tp = price - 4.5 * current_atr
                modify_take_profit(sym, side, new_tp, abs(qty))
                await notify_sl_tp_update(sym, side, "tp", new_tp)

            _last_update[sym] = now

    except Exception as e:
        logger.error(f"[manage] Error: {e}")
        await notify_error(f"⚠️ TradeManager Error: {e}")

async def manage_open_trades_loop(interval: int = 20):
    """לולאת ניהול חי ברקע"""
    while True:
        await manage_open_trades()
        await asyncio.sleep(interval)

async def daily_summary():
    """סיכום יומי: רווח/הפסד, טריידים, הערות"""
    try:
        summary = {
            "pnl": _daily_pnl,
            "trades": _trades_today,
            "time": time.strftime("%d/%m/%Y %H:%M")
        }
        with open(REVIEW_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        await notify_daily_summary(summary)
    except Exception as e:
        await notify_error(f"Daily summary failed: {e}")

async def heartbeat_loop(interval: int = 3600):
    """כל שעה שולח Heartbeat"""
    while True:
        await notify_heartbeat()
        await asyncio.sleep(interval)

async def panic_close_all():
    """סוגר את כל הפוזיציות מיידית"""
    try:
        close_all_positions()
        await notify_info("🛑 Panic Button: כל הפוזיציות נסגרו!")
    except Exception as e:
        await notify_error(f"Panic close failed: {e}")





