# utils/trade_manager.py
from __future__ import annotations
import time, logging, asyncio, json, os
from pathlib import Path
from typing import Dict, Any, List

from utils import ws_fallback
from utils.indicators import atr, macd, adx
from utils.binance_client import (
    modify_stop_loss, modify_take_profit,
    get_open_positions, get_klines_df, close_all_positions,
)

# נסה לייבא כלים אופציונליים אם קיימים
try:
    from utils.binance_client import futures_mark_price, get_open_orders
except Exception:
    futures_mark_price = None
    get_open_orders = None

try:
    from utils.binance_client import set_breakeven_stop as _set_be_native
except Exception:
    _set_be_native = None

from utils.config import ALLOW_MANAGE_OPEN_TRADES, AUTO_RUN
from utils.telegram_notifier import (
    notify_sl_tp_update, notify_info,
    notify_error, notify_heartbeat,
    notify_daily_summary, notify_trade_review
)

logger = logging.getLogger("algogpt.trade_manager")

# === תצורה דינמית מה-ENV ===
_COOLDOWN = int(os.getenv("TM_UPDATE_COOLDOWN_SEC", "30"))
_BE_GUARD_ENABLE = os.getenv("BE_GUARD_ENABLE", "1").lower() in ("1", "true", "yes")
_BE_GUARD_EVERY_SEC = int(os.getenv("BE_GUARD_EVERY_SEC", "30"))
_TP1_TAGS: List[str] = [t.strip() for t in os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1").split(",") if t.strip()]

# === Daily Cap / KillSwitch ===
DAILY_LOSS_CAP = float(os.getenv("DAILY_HARD_LOSS_USD", "-150"))
_daily_pnl = 0.0
_trades_today: list[dict] = []
_cap_triggered = False

# Kill-Switch tracking
_health_fails = 0
_HEALTH_FAIL_MAX = int(os.getenv("KILLSWITCH_THRESHOLD", "3"))

REVIEW_PATH = Path("static/cache/trade_reviews.json")

_last_update: Dict[str, float] = {}
_last_be_guard = 0.0
_be_set_once: set[str] = set()  # symbols שקיבלו BE במחזור חיי הפוזיציה

def _tp1_pct_default() -> float:
    """שולף את TP1 ברירת-המחדל מתוך LADDER_TP_DEFAULT_PCTS (ב-ENV)."""
    csv = os.getenv("LADDER_TP_DEFAULT_PCTS", "1.8,3.2,5.5")
    try:
        arr = [float(x) for x in csv.split(",") if x.strip()]
        return min(arr) if arr else 1.8
    except Exception:
        return 1.8

async def manage_open_trades():
    """ניהול דינמי חי של טריידים פתוחים (SL, TP, BE, Trailing)."""
    global _daily_pnl, _cap_triggered
    if not ALLOW_MANAGE_OPEN_TRADES or _cap_triggered:
        return

    try:
        positions = get_open_positions()
        now = time.time()
        for pos in positions:
            sym = pos.get("symbol")
            qty = float(pos.get("positionAmt") or 0)
            entry = float(pos.get("entryPrice") or 0)
            side = "LONG" if qty > 0 else "SHORT"
            price = ws_fallback.get_price(sym) or float(pos.get("markPrice") or 0)
            if price <= 0 or entry <= 0 or abs(qty) <= 0:
                continue

            # Cooldown פר-סימבול
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

            # === Breakeven SL (תנאים רכים) ===
            be_trigger = float(os.getenv("TM_BE_MIN_PROFIT_PCT", "1.5"))
            if profit_pct >= be_trigger and (macd_now > 0 or current_adx > 20):
                new_sl = entry
                if _set_be_native:
                    try:
                        await _set_be_native(sym, side, entry)
                        await notify_sl_tp_update(sym, side, "breakeven", entry)
                    except Exception as e:
                        logger.error("[manage] native BE failed: %s", e)
                else:
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

            # === Dynamic TP (מותאם תנופה) ===
            if current_adx > 25 and macd_now > 0:
                if side == "LONG":
                    new_tp = price + 4.5 * current_atr
                else:
                    new_tp = price - 4.5 * current_atr
                modify_take_profit(sym, side, new_tp, abs(qty))
                await notify_sl_tp_update(sym, side, "tp", new_tp)

            _last_update[sym] = now

        # === שומר Breakeven “דליל” (אופציונלי) ===
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
            "time": time.strftime("%d/%m/%Y %H:%M"),
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

def record_health(ok: bool):
    """רישום כשלי /health → KillSwitch"""
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
    נקרא כשפקודה מולאה. אם ה-clientOrderId מכיל תגית TP1 → מרים BE אוטומטי.
    דורש שתגיות TP1 יופיעו ב-ENV: TP1_TAGS (למשל 'TP1,tp1,tp_1').
    """
    try:
        clid = (event.get("clientOrderId") or "").upper()
        symbol = (event.get("symbol") or "").upper()
        if not symbol or not clid:
            return

        is_tp1 = any(tag.upper() in clid for tag in _TP1_TAGS)
        if not is_tp1:
            return

        # BE לפי יכולת מקורית אם קיימת, אחרת fallback
        if _set_be_native:
            # הצד נדרש: נניח מהאירוע, ואם לא — נגזור לפי כמות בפוזיציה
            side = (event.get("side") or "LONG").upper()
            await _set_be_native(symbol, side)
            await notify_sl_tp_update(symbol, side, "breakeven", "entry±offset")
        else:
            # fallback: נניח שיש לנו נתוני פוזיציה לקבלת entry/qty
            for pos in get_open_positions(symbol):
                amt = float(pos.get("positionAmt", "0"))
                if abs(amt) < 1e-12:
                    continue
                side = "LONG" if amt > 0 else "SHORT"
                entry = float(pos.get("entryPrice", "0"))
                if entry <= 0:
                    continue
                modify_stop_loss(symbol, side, entry, abs(amt))
                await notify_sl_tp_update(symbol, side, "breakeven", entry)
                break
    except Exception as e:
        logger.error("[tm.order_filled] error: %s", e)

# ===================== “שומר BE” אופציונלי ודליל =====================
async def _be_guard_tick():
    """בכל BE_GUARD_EVERY_SEC: אם המחיר עבר TP1% ועדיין אין BE, נרים BE פעם אחת."""
    global _last_be_guard
    now = time.time()
    if now - _last_be_guard < _BE_GUARD_EVERY_SEC:
        return
    _last_be_guard = now

    if not futures_mark_price or not get_open_orders:
        return  # אין כלים לביצוע שומר; דלג

    tp1_pct = _tp1_pct_default() / 100.0
    positions = get_open_positions()
    for pos in positions:
        try:
            symbol = (pos.get("symbol") or "").upper()
            if not symbol:
                continue
            amt = float(pos.get("positionAmt", "0"))
            if abs(amt) < 1e-12:
                continue
            entry = float(pos.get("entryPrice", "0"))
            if entry <= 0:
                continue
            side = "LONG" if amt > 0 else "SHORT"

            mark = futures_mark_price(symbol) or 0.0
            if mark <= 0:
                continue

            reached = (mark >= entry * (1.0 + tp1_pct)) if side == "LONG" else (mark <= entry * (1.0 - tp1_pct))
            if not reached:
                continue

            # אם כבר יש SL ברמת BE ומעלה — לא צריך
            orders = get_open_orders(symbol) or []
            be_like = False
            for o in orders:
                otype = (o.get("type") or "").upper()
                if "STOP" not in otype:
                    continue
                stop_px = float(o.get("stopPrice") or o.get("price") or 0)
                if side == "LONG" and stop_px >= entry:
                    be_like = True
                if side == "SHORT" and stop_px <= entry:
                    be_like = True
            if be_like:
                continue

            # אל תבצע פעמיים עד סגירת הפוזיציה
            if symbol in _be_set_once:
                continue

            # בצע BE עם native אם יש, אחרת fallback
            if _set_be_native:
                await _set_be_native(symbol, side)
                await notify_sl_tp_update(symbol, side, "breakeven", "entry±offset")
            else:
                modify_stop_loss(symbol, side, entry, abs(amt))
                await notify_sl_tp_update(symbol, side, "breakeven", entry)

            _be_set_once.add(symbol)
            logger.info("[tm.be_guard] %s BE set", symbol)
        except Exception as e:
            logger.error("[tm.be_guard] error: %s", e)







