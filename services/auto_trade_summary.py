# services/auto_trade_summary.py
from __future__ import annotations
import logging
from utils.pnl_tracker import get_last_trade
from utils.telegram_notifier import notify_telegram

logger = logging.getLogger("algogpt.auto_summary")

async def post_trade_summary():
    trade = get_last_trade()
    if not trade:
        return
    msg = (
        f"📊 סיכום טרייד\n"
        f"סימבול: {trade['symbol']}\n"
        f"כיוון: {trade['side']}\n"
        f"כניסה: {trade['entry_price']}\n"
        f"יציאה: {trade['exit_price']}\n"
        f"PnL: {trade['pnl_usd']:.2f} USDT\n"
        f"ציון AI: {trade.get('ai_score','-')}\n"
        f"Review: {trade.get('review','')}"
    )
    await notify_telegram(msg)
    logger.info({"event": "trade_summary_sent", "symbol": trade["symbol"]})


