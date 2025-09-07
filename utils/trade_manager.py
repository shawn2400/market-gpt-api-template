# utils/trade_manager.py
from __future__ import annotations
import time, logging, asyncio, json, os
from pathlib import Path
from typing import Dict, Any, List, Optional

from utils import ws_fallback
from utils.indicators import atr, macd, adx
from utils.binance_client import (
    modify_stop_loss, modify_take_profit,
    get_open_positions, get_klines_df, close_all_positions,
    futures_mark_price, get_open_orders, set_breakeven_stop,
)

from utils.config import ALLOW_MANAGE_OPEN_TRADES
from utils.telegram_notifier import (
    notify_sl_tp_update, notify_info,
    notify_error, notify_heartbeat,
    notify_daily_summary
)

logger = logging.getLogger("algogpt.trade_manager")

# === ENV ===
_COOLDOWN = int(os.getenv("TM_UPDATE_COOLDOWN_SEC", "30"))
_BE_GUARD_ENABLE = str(os.getenv("BE_GUARD_ENABLE", "1")).lower() in ("1","true","yes","on")
_BE_GUARD_EVERY_SEC = int(os.getenv("BE_GUARD_EVERY_SEC", "30"))
_TP1_TAGS: List[str] = [t.strip() for t in os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1").split(",") if t.strip()]

# Trailing
_TRAIL_ATR_MULT = float(os.getenv("TRAIL_ATR_MULT", "1.5"))

# Daily cap / KillSwitch
DAILY_LOSS_CAP = float(os.getenv("DAILY_HARD_LOSS_USD", "-150"))
_HEALTH_FAIL_MAX = int(os.getenv("KILLSWITCH_THRESHOLD", "3"))

# BE params
_BE_OFFSET_BPS = float(os.getenv("TP_BE_OFFSET_BPS", "5"))  # מרחק מ-Entry בבייסיס פוינט
_BE_ONLY_AFTER_TP1 = str(os.getenv("TP_BE_ONLY_AFTER_TP1", "1")).lower() not in ("0","false","no")

REVIEW_PATH = Path("static/cache/trade_reviews.json")

_daily_pnl = 0.0
_trades_today: list[dict] = []
_cap_triggered = False

_health_fails = 0
_last_update: Dict[str, float] = {}
_last_be_guard = 0.0
_be_set_once: set[str] = set()  # סימבולים שקיבלו BE פעם אחת במחזור הפוזיציה

def _tp1_pct_default() -> float:
    csv = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
    try:
        arr = [float(x) for x in csv.split(",") if x.strip()]
        return min(arr) if arr else 1.8
    except Exception:
        return 1.8

async def _to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)

async def manage_open_trades():
    """ניהול חי: SL/TP/BE/Trailing – לא חונק את event loop (קריאות חסימה עטופות)."""
    global _daily_pnl, _cap_triggered
    if not ALLOW_MANAGE_OPEN_TRADES or _cap_triggered:
        return

    try:
        positions = await _to_thread(get_open_positions)
        now = time.time()

        for pos in positions:
            try:
                sym = (pos.get("symbol") or "").upper()
                qty = float(pos.get("positionAmt") or 0)
                entry = float(pos.get("entryPrice") or 0)
                if not sym or entry <= 0 or abs(qty) <= 0:
                    continue
                side = "LONG" if qty > 0 else "SHORT"

                # Cooldown פר-סימבול
                if now - _last_update.get(sym, 0) < _COOLDOWN:
                    continue

                # מחיר נוכחי
                price = ws_fallback.get_price(sym) or (await _to_thread(futures_mark_price, sym)) or 0.0
                if price <= 0:
                    continue

                # נתוני נרות למדדים
                df = await _to_thread(get_klines_df, sym, "5m", 50)
                if df is None or getattr(df, "empty", True):
                    continue

                current_atr = float(atr(df)[-1])
                current_adx = float(adx(df)[-1])
                macd_line, macd_signal, _ = macd(df["close"])
                macd_now = float(macd_line.iloc[-1] - macd_signal.iloc[-1])
                profit_pct = abs((price - entry) / entry) * 100

                # === BE “רך” כאשר הרווח מעל סף והאינדיקציות לא נגד
                be_trigger = float(os.getenv("TM_BE_MIN_PROFIT_PCT", "1.5"))
                if (not _BE_ONLY_AFTER_TP1) and profit_pct >= be_trigger and (macd_now > 0 or current_adx > 20):
                    try:
                        await _to_thread(set_breakeven_stop, sym, _BE_OFFSET_BPS)
                        await notify_sl_tp_update(sym, side, "breakeven", f"entry±{_BE_OFFSET_BPS}bps")
                        _be_set_once.add(sym)
                    except Exception as e:
                        logger.error("[manage] BE set failed: %s", e)

                # === Trailing SL (לפי ATR)
                if side == "LONG":
                    recent_low = float(df["low"].iloc[-3:].min())
                    trail_sl = recent_low - _TRAIL_ATR_MULT * current_atr
                else:
                    recent_high = float(df["high"].iloc[-3:].max())
                    trail_sl = recent_high + _TRAIL_ATR_MULT * current_atr

                await _to_thread(modify_stop_loss, sym, trail_sl, side, None, abs(qty))
                await notify_sl_tp_update(sym, side, "trailing", trail_sl)

                # === Dynamic TP (כשיש תנופה)
                if current_adx > 25 and macd_now > 0:
                    if side == "LONG":
                        new_tp = price + 4.5 * current_atr
                    else:
                        new_tp = price - 4.5 * current_atr
                    await _to_thread(modify_take_profit, sym, new_tp, side, None, abs(qty))
                    await notify_sl_tp_update(sym, side, "tp", new_tp)

                _last_update[sym] = now

            except Exception as e:
                logger.error("[manage] per-position error %s: %s", pos.get("symbol"), e)

        # === “שומר BE” דליל: רק אחרי TP1% ובתנאי שאין BE דומה כבר ===
        if _BE_GUARD_ENABLE:
            await _be_guard_tick()

        # === Daily Cap ===
        if _daily_pnl <= DAILY_LOSS_CAP and not _cap_triggered:
            _cap_triggered = True
            await panic_close_all()
            await notify_error(f"🚨 Daily loss cap hit ({_daily_pnl:.2f} USDT) → AUTO_RUN disabled")
            os.environ["AUTO_RUN"] = "0"

    except Exception as e:
        logger.error(f"[manage] Error: {e}")
        await notify_error(f"⚠️ TradeManager Error: {e}")

async def manage_open_trades_loop(interval: int = 20):
    """לולאת ניהול ברקע"""
    while True:
        await manage_open_trades()
        await asyncio.sleep(interval)

async def daily_summary():
    """סיכום יומי לקובץ + טלגרם"""
    try:
        summary = {
            "pnl": _daily_pnl,
            "trades": _trades_today,
            "time": time.strftime("%d/%m/%Y %H:%M"),
        }
        REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REVIEW_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        await notify_daily_summary(summary)
    except Exception as e:
        await notify_error(f"Daily summary failed: {e}")

async def heartbeat_loop(interval: int = 3600):
    while True:
        await notify_heartbeat()
        await asyncio.sleep(interval)

async def panic_close_all():
    """סוגר את כל הפוזיציות מיידית (threadpool)"""
    try:
        await _to_thread(close_all_positions)
        await notify_info("🛑 Panic Button: כל הפוזיציות נסגרו!")
    except Exception as e:
        await notify_error(f"Panic close failed: {e}")

def record_health(ok: bool):
    """מעקב אחר /health -> KillSwitch"""
    global _health_fails, _cap_triggered
    if ok:
        _health_fails = 0
        return
    _health_fails += 1
    if _health_fails >= _HEALTH_FAIL_MAX and not _cap_triggered:
        _cap_triggered = True
        asyncio.create_task(panic_close_all())
        logger.error("🚨 KillSwitch triggered — too many /health fails")

# ===================== אירוע מילוי פקודה (TP1 Tag) =====================
async def handle_order_filled(event: Dict[str, Any]):
    """
    אם ה-clientOrderId מכיל תגית TP1 → BE אוטומטי.
    התגיות נקבעות ב-ENV: TP1_TAGS (למשל 'TP1,tp1,tp_1').
    """
    try:
        clid = (event.get("clientOrderId") or "").upper()
        symbol = (event.get("symbol") or "").upper()
        if not symbol or not clid:
            return

        is_tp1 = any(tag.upper() in clid for tag in _TP1_TAGS)
        if not is_tp1:
            return

        # אם כבר בוצע BE במחזור – דלג
        if symbol in _be_set_once:
            return

        # BE עם offset מה-ENV
        await _to_thread(set_breakeven_stop, symbol, _BE_OFFSET_BPS)
        await notify_sl_tp_update(symbol, "?", "breakeven", f"entry±{_BE_OFFSET_BPS}bps")
        _be_set_once.add(symbol)

    except Exception as e:
        logger.error("[tm.order_filled] error: %s", e)

# ===================== BE Guard דליל =====================
async def _be_guard_tick():
    """בכל BE_GUARD_EVERY_SEC: אם המחיר עבר TP1% ואין BE דומה – נרים BE פעם אחת."""
    global _last_be_guard
    now = time.time()
    if now - _last_be_guard < _BE_GUARD_EVERY_SEC:
        return
    _last_be_guard = now

    try:
        positions = await _to_thread(get_open_positions)
        tp1_pct = _tp1_pct_default() / 100.0

        for pos in positions:
            try:
                symbol = (pos.get("symbol") or "").upper()
                amt = float(pos.get("positionAmt", "0"))
                if not symbol or abs(amt) < 1e-12:
                    continue
                entry = float(pos.get("entryPrice", "0"))
                if entry <= 0:
                    continue
                side = "LONG" if amt > 0 else "SHORT"

                mark = (await _to_thread(futures_mark_price, symbol)) or 0.0
                if mark <= 0:
                    continue

                reached = (mark >= entry * (1.0 + tp1_pct)) if side == "LONG" else (mark <= entry * (1.0 - tp1_pct))
                if not reached:
                    continue

                # אם כבר יש SL דמוי-BE – דלג
                orders = await _to_thread(get_open_orders, symbol)
                be_like = False
                for o in (orders or []):
                    otype = (o.get("type") or "").upper()
                    if "STOP" not in otype:
                        continue
                    stop_px = float(o.get("stopPrice") or o.get("price") or 0)
                    if side == "LONG" and stop_px >= entry:
                        be_like = True
                        break
                    if side == "SHORT" and stop_px <= entry:
                        be_like = True
                        break
                if be_like:
                    continue

                if symbol in _be_set_once:
                    continue

                await _to_thread(set_breakeven_stop, symbol, _BE_OFFSET_BPS)
                await notify_sl_tp_update(symbol, side, "breakeven", f"entry±{_BE_OFFSET_BPS}bps")
                _be_set_once.add(symbol)
                logger.info("[tm.be_guard] %s BE set", symbol)

            except Exception as e:
                logger.error("[tm.be_guard] per-symbol error: %s", e)

    except Exception as e:
        logger.error("[tm.be_guard] error: %s", e)








