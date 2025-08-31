# utils/telegram_api.py
from __future__ import annotations

import inspect
from typing import Any, Dict, Optional, Tuple

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes, Application

from utils.runtime_prefs import TelePrefs

# נסיון לייבא get_trade_by_id – קיים אצלך ב-trade_storage (או trade_store fallback)
try:
    from utils.trade_storage import get_trade_by_id  # type: ignore
except Exception:  # pragma: no cover
    from utils.trade_store import get_trade_by_id  # type: ignore

tprefs = TelePrefs()


# ----------------- Helpers -----------------
def _fmt_usd(x: float) -> str:
    return f"${x:,.2f}"


def _calc_size(entry: float, sl: float, leverage: int, budget_usd: float, risk_pct: float) -> Tuple[float, float, float]:
    """
    מחזיר: (qty, notional, margin)
    - qty לפי מגבלת סיכון כספי: risk_dollars = budget * (risk_pct/100)
      qty_risk = risk_dollars / |entry - sl|
    - מגבלת מרג'ין: margin = (entry * qty) / leverage <= budget  =>  qty_margin = (budget * leverage) / entry
    - qty סופי = min(qty_risk, qty_margin)
    """
    entry = float(entry)
    sl = float(sl)
    leverage = max(1, int(leverage))
    budget_usd = max(1e-6, float(budget_usd))
    risk_dollars = max(0.0, budget_usd * float(risk_pct) / 100.0)
    delta = abs(entry - sl)
    if delta <= 0:
        raise ValueError("SL ו-Entry חייבים להיות שונים.")

    qty_risk = risk_dollars / delta
    qty_margin = (budget_usd * leverage) / entry
    qty = max(0.0, min(qty_risk, qty_margin))
    notional = qty * entry
    margin = notional / leverage
    return qty, notional, margin


async def _get_trade(trade_id: str) -> Optional[Dict[str, Any]]:
    """תמיכה גם בפונקציה sync וגם async של get_trade_by_id."""
    res = get_trade_by_id(trade_id)
    if inspect.isawaitable(res):
        return await res  # type: ignore
    return res  # type: ignore


# ----------------- Commands -----------------
async def cmd_pin_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args or args[0].lower() not in ("on", "off"):
        await update.message.reply_text("שימוש: /pin_summary on|off")
        return
    on = args[0].lower() == "on"
    await tprefs.set_pin_summary(chat_id, on)
    if on:
        msg = await update.message.reply_text("📌 סיכום מוצמד יופיע כאן. המערכת תעדכן בהמשך ב־edit.")
        await tprefs.set_pin_message_id(chat_id, msg.message_id)
        try:
            await context.bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
        except Exception:
            pass
    else:
        await tprefs.set_pin_message_id(chat_id, None)
    await update.message.reply_text(f"pin_summary: {'ON' if on else 'OFF'}")


async def cmd_bundle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        sec = await tprefs.get_bundle_window(chat_id)
        await update.message.reply_text(f"bundle={sec}s  (שימוש: /bundle <seconds>, 0=כבוי)")
        return
    try:
        seconds = max(0, int(args[0]))
    except ValueError:
        await update.message.reply_text("שימוש: /bundle <seconds>  (למשל /bundle 60)")
        return
    await tprefs.set_bundle_window(chat_id, seconds)
    await update.message.reply_text(f"Bundling {'ON' if seconds>0 else 'OFF'} ({seconds}s)")


async def cmd_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("שימוש: /snooze <minutes> <trade_id>")
        return
    try:
        minutes = int(args[0])
    except ValueError:
        await update.message.reply_text("minutes חייב להיות מספר שלם.")
        return
    trade_id = args[1]
    await tprefs.snooze_trade(trade_id, minutes)
    await update.message.reply_text(f"🔕 Snooze לטרייד {trade_id} ל-{minutes} דק׳ הופעל.")


async def cmd_snooze_sym(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("שימוש: /snooze_sym <symbol> <minutes>")
        return
    symbol = args[0].upper()
    try:
        minutes = int(args[1])
    except ValueError:
        await update.message.reply_text("minutes חייב להיות מספר שלם.")
        return
    await tprefs.snooze_symbol(symbol, minutes)
    await update.message.reply_text(f"🔕 Snooze לסימבול {symbol} ל-{minutes} דק׳ הופעל.")


async def cmd_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("שימוש: /size <trade_id> <risk_pct> (למשל /size abc123 1.25)")
        return
    trade_id = args[0]
    try:
        risk_pct = float(args[1])
    except ValueError:
        await update.message.reply_text("risk_pct חייב להיות מספר (אפשר עשרוני).")
        return

    trade = await _get_trade(trade_id)  # מצופה: {symbol, entry, sl, leverage, budget}
    if not trade:
        await update.message.reply_text(f"לא נמצא טרייד id={trade_id}")
        return

    entry = float(trade["entry"])
    sl = float(trade["sl"])
    lev = int(trade.get("leverage", 10))
    budget = float(trade.get("budget", 30.0))
    qty, notional, margin = _calc_size(entry, sl, lev, budget, risk_pct)

    text = (
        f"🧮 *Position Size*\n"
        f"ID: `{trade_id}` | {trade.get('symbol','?')}\n"
        f"Risk: {risk_pct:.2f}% מתוך Budget={_fmt_usd(budget)}\n"
        f"Entry={entry:.6f}  SL={sl:.6f}  Lev=x{lev}\n"
        f"*Qty*={qty:.6f}\n"
        f"Notional≈{_fmt_usd(notional)} | Margin≈{_fmt_usd(margin)}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


def register_light_handlers(app: Application) -> None:
    """
    רישום פקודות לבוט. קרא מפונקציית ההקמה של ה-Application.
    """
    app.add_handler(CommandHandler("pin_summary", cmd_pin_summary))
    app.add_handler(CommandHandler("bundle", cmd_bundle))
    app.add_handler(CommandHandler("snooze", cmd_snooze))
    app.add_handler(CommandHandler("snooze_sym", cmd_snooze_sym))
    app.add_handler(CommandHandler("size", cmd_size))


