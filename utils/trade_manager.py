# utils/trade_manager.py
from __future__ import annotations
import time, logging, asyncio, json, os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

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

# BE native (סינכרוני)
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
def _to_bool(v: Optional[str], default: bool=False) -> bool:
    if v is None: return default
    return str(v).strip().lower() in ("1","true","yes","on")

_COOLDOWN = int(os.getenv("TM_UPDATE_COOLDOWN_SEC", "30"))

_BE_GUARD_ENABLE      = _to_bool(os.getenv("BE_GUARD_ENABLE", "1"), True)
_BE_GUARD_EVERY_SEC   = int(os.getenv("BE_GUARD_EVERY_SEC", "30"))
_TP_BE_ONLY_AFTER_TP1 = _to_bool(os.getenv("TP_BE_ONLY_AFTER_TP1", "1"), True)
_TP_BE_OFFSET_BPS     = float(os.getenv("TP_BE_OFFSET_BPS", "5"))

_TP1_TAGS: List[str] = [
    t.strip() for t in os.getenv("TP1_TAGS", "TP1,tp1,tp_1,TAKE_PROFIT_1").split(",") if t.strip()
]

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
_be_set_once: Set[str] = set()  # סימבולים שקיבלו BE במחזור חיי הפוזיציה

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
            sym = (pos.get("symbol") or "").upper()
            qty = float(pos.get("positionAmt") or 0.0)
            entry = float(pos.get("entryPrice") or 0.0)
            side = "LONG" if qty > 0 else "SHORT"
            price = ws_fallback.get_price(sym) or float(pos.get("markPrice") or 0.0)

            if not sym or price <= 0 or entry <= 0 or abs(qty) <= 0:
                continue

            # Cooldown פר-סימבול
            if now - _last_update.get(sym, 0.0) < _COOLDOWN:
                continue

            df = get_klines_df(sym, interval="5m", limit=50)
            if df is None or df.empty:
                continue

            current_atr = atr(df)[-1]
            current_adx = adx(df)[-1]
            macd_line, macd_signal, _ = macd(df["close"])
            macd_now = macd_line.iloc[-1] - macd_signal.iloc[-1]
            profit_pct = abs((price - entry) / entry) * 100.0

            # === Breakeven SL (תנאים רכים) ===
            be_trigger = float(os.getenv("TM_BE_MIN_PROFIT_PCT", "1.5"))
            if profit_pct >= be_trigger and (macd_now > 0 or current_adx > 20):
                # שימוש ב-native אם קיים, אחרת fallback
                try:
                    if _set_be_native:
                        _set_be_native(sym, offset_bps=_TP_BE_OFFSET_BPS)
                        await notify_sl_tp_update(sym, side, "breakeven", f"entry±{_TP_BE_OFFSET_BPS}bps")
                    else:
                        # Fallback חתימה תקינה: price קודם, ואז side/quantity
                        modify_stop_loss(sym, entry, position_side=side, quantity=abs(qty))
                        await notify_sl_tp_update(sym, side, "breakeven", entry)
                    _be_set_once.add(sym)
                except Exception as e:
                    logger.error("[manage] BE set failed: %s", e)

            # === Trailing SL (מבוסס ATR) ===
            try:
                if side == "LONG":
                    recent_low = df["low"].iloc[-3:].min()
                    trail_sl = recent_low - 0.6 * current_atr
                else:
                    recent_high = df["high"].iloc[-3:].max()
                    trail_sl = recent_high + 0.6 * current_atr

                modify_stop_loss(sym, trail_sl, position_side=side, quantity=abs(qty))
                await notify_sl_tp_update(sym, side, "trailing", trail_sl)
            except Exception as e:
                logger.error("[manage] trailing SL failed: %s", e)

            # === Dynamic TP (תנופה) ===
            if current_adx > 25 and macd_now > 0:
                try:
                    new_tp = (price + 4.5 * current_atr) if side == "LONG" else (price - 4.5 * current_atr)
                    modify_take_profit(sym, new_tp, position_side=side, quantity=abs(qty))
                    await notify_sl_tp_update(sym, side, "tp", new_tp)
                except Exception as e:
                    logger.error("[manage] dynamic TP failed: %s", e)

            _last_update[sym] = now

        # === “שומר BE” דליל (אופציונלי) ===
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
        REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    דורש תגיות TP1 ב-ENV: TP1_TAGS (למשל 'TP1,tp1,tp_1,TAKE_PROFIT_1').
    """
    try:
        clid = (event.get("clientOrderId") or "").upper()
        symbol = (event.get("symbol") or "").upper()
        if not symbol or not clid:
            return

        # בדיקת תגית TP1
        is_tp1 = any(tag.upper() in clid for tag in _TP1_TAGS)
        if not is_tp1:
            return

        # אל תעשה כפול אם כבר הוגדר BE לסימבול
        if symbol in _be_set_once:
            return

        # BE אחרי TP1 (או תמיד—אם כיבית את TP_BE_ONLY_AFTER_TP1)
        if _TP_BE_ONLY_AFTER_TP1:
            # זה כבר TP1; אפשר להרים BE
            pass

        # בצע BE (native עדיף, אחרת fallback)
        if _set_be_native:
            _set_be_native(symbol, offset_bps=_TP_BE_OFFSET_BPS)
            await notify_sl_tp_update(symbol, "UNKNOWN", "breakeven", f"entry±{_TP_BE_OFFSET_BPS}bps")
        else:
            # Fallback לפי פוזיציה
            for pos in get_open_positions(symbol):
                amt = float(pos.get("positionAmt", "0"))
                if abs(amt) < 1e-12:
                    continue
                side = "LONG" if amt > 0 else "SHORT"
                entry = float(pos.get("entryPrice", "0"))
                if entry <= 0:
                    continue
                modify_stop_loss(symbol, entry, position_side=side, quantity=abs(amt))
                await notify_sl_tp_update(symbol, side, "breakeven", entry)
                break

        _be_set_once.add(symbol)
        logger.info("[tm.order_filled] %s BE set after TP1", symbol)

    except Exception as e:
        logger.error("[tm.order_filled] error: %s", e)

# ===================== “שומר BE” אופציונלי ודליל =====================
async def _be_guard_tick():
    """בכל BE_GUARD_EVERY_SEC: אם המחיר עבר TP1% (או שאינך דורש TP1) ועדיין אין BE, נרים BE פעם אחת."""
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
            if not symbol or symbol in _be_set_once:
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

            # אם דורשים BE רק אחרי TP1: נבדוק שהמחיר עבר TP1%
            if _TP_BE_ONLY_AFTER_TP1:
                reached = (mark >= entry * (1.0 + tp1_pct)) if side == "LONG" else (mark <= entry * (1.0 - tp1_pct))
                if not reached:
                    continue

            # אם כבר יש SL ברמת BE ומעלה — לא צריך
            orders = get_open_orders(symbol) or []
            be_like = False
            for o in orders:
                otype = (o.get("type") or o.get("origType") or "").upper()
                if "STOP" not in otype:
                    continue
                stop_px = float(o.get("stopPrice") or o.get("price") or 0)
                if side == "LONG" and stop_px >= entry: be_like = True
                if side == "SHORT" and stop_px <= entry: be_like = True
            if be_like:
                continue

            # בצע BE
            if _set_be_native:
                _set_be_native(symbol, offset_bps=_TP_BE_OFFSET_BPS)
                await notify_sl_tp_update(symbol, side, "breakeven", f"entry±{_TP_BE_OFFSET_BPS}bps")
            else:
                modify_stop_loss(symbol, entry, position_side=side, quantity=abs(amt))
                await notify_sl_tp_update(symbol, side, "breakeven", entry)

            _be_set_once.add(symbol)
            logger.info("[tm.be_guard] %s BE set", symbol)
        except Exception as e:
            logger.error("[tm.be_guard] error: %s", e)








