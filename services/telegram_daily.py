# services/telegram_daily.py
from __future__ import annotations
import asyncio, logging
from datetime import datetime
from utils.pnl_summary import get_pnl_summary
from utils.telegram_notifier import notify_telegram

logger = logging.getLogger("algogpt.telegram_daily")

async def start_daily_summaries():
    while True:
        now = datetime.utcnow()
        if now.hour == 21 and now.minute < 2:  # 23:00 שעון ישראל בערך
            try:
                summary = get_pnl_summary(days=1)
                msg = (
                    f"📅 סיכום יומי {now.date()}\n"
                    f"טריידים: {summary['total_trades']}\n"
                    f"PnL: {summary['realized_pnl_usd']:.2f} USDT\n"
                    f"WinRate: {summary['win_rate']}%\n"
                )
                await notify_telegram(msg)
            except Exception as e:
                logger.error({"event": "daily_summary_failed", "error": str(e)})
        await asyncio.sleep(60)


