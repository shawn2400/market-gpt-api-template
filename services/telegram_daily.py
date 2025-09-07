# services/telegram_daily.py
from __future__ import annotations
import datetime as dt
from utils.pnl_tracker import get_pnl_summary
from utils.metrics import metrics_tracker
from utils.telegram_notifier import send_telegram_message

async def send_heartbeat():
    msg = f"💓 Heartbeat {dt.datetime.utcnow().isoformat()}"
    await send_telegram_message(msg)

async def send_daily_summary():
    pnl = get_pnl_summary(days=1)
    m = metrics_tracker.get_metrics()
    msg = (
        f"📊 Daily Summary\n"
        f"Trades: {pnl['total_trades']} | WinRate: {pnl['win_rate']}%\n"
        f"PnL: {pnl['realized_pnl_usd']} USDT\n"
        f"Errors: {m['requests']['errors_total']}\n"
        f"Latency p95: {m['latency_ms']['p95']}ms"
    )
    await send_telegram_message(msg)

async def send_weekly_summary():
    pnl = get_pnl_summary(days=7)
    msg = (
        f"📊 Weekly Summary\n"
        f"Trades: {pnl['total_trades']} | WinRate: {pnl['win_rate']}%\n"
        f"PnL: {pnl['realized_pnl_usd']} USDT"
    )
    await send_telegram_message(msg)

async def send_monthly_summary():
    pnl = get_pnl_summary(days=30)
    msg = (
        f"📊 Monthly Summary\n"
        f"Trades: {pnl['total_trades']} | WinRate: {pnl['win_rate']}%\n"
        f"PnL: {pnl['realized_pnl_usd']} USDT"
    )
    await send_telegram_message(msg)

