# services/auto_trade_summary.py
from __future__ import annotations
import datetime as dt
from utils.telegram_notifier import send_telegram_message

async def send_trade_summary(trade: dict) -> None:
    """
    סיכום מידי של טרייד אחד — נשלח לטלגרם.
    trade dict דוגמה:
    {
      "symbol": "BTCUSDT", "side": "LONG", "leverage": 20,
      "entry": 27000, "exit": 27250, "pnl": 125.5,
      "rr": 2.1, "sl": 26500, "tp": 27500
    }
    """
    ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    pnl_txt = f"{trade.get('pnl', 0):+.2f} USDT"
    rr_txt = f"RR={trade.get('rr', '-')}"
    msg = (
        f"✅ Trade Closed [{ts}]\n"
        f"{trade['symbol']} {trade['side']} x{trade['leverage']}\n"
        f"Entry: {trade['entry']} | Exit: {trade.get('exit','-')}\n"
        f"PnL: {pnl_txt} | {rr_txt}\n"
        f"SL={trade.get('sl','-')} | TP={trade.get('tp','-')}"
    )
    await send_telegram_message(msg)

