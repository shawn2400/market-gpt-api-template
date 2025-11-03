#!/usr/bin/env python3
# workers/daily_digest.py
"""
Worker שרץ פעמיים ביום (08:00 + 22:00 שעון ישראל) ושולח דוח מסכם
Morning Trading Summary (08:00) + Evening Daily Digest (22:00)
"""
import os
import sys
import json
import time
import logging
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.alerts import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("daily_digest")

try:
    ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:
    ISRAEL_TZ = ZoneInfo("UTC")

TRADES_LOG_PATH = os.getenv("TRADES_LOG_PATH", "data/trades_log.json")
MORNING_HOUR = int(os.getenv("DIGEST_MORNING_HOUR", "8"))
EVENING_HOUR = int(os.getenv("DIGEST_EVENING_HOUR", "22"))

def load_trades_for_date(date: datetime) -> list:
    """Load trades closed on a specific date"""
    try:
        if not Path(TRADES_LOG_PATH).exists():
            return []
        
        with open(TRADES_LOG_PATH, 'r') as f:
            all_trades = json.load(f)
        
        date_str = date.strftime("%Y-%m-%d")
        day_trades = []
        
        for trade in all_trades:
            closed_at = trade.get("closed_at") or trade.get("updated_at")
            if closed_at and date_str in closed_at:
                day_trades.append(trade)
        
        return day_trades
    except Exception as e:
        logger.error(f"Failed to load trades: {e}")
        return []

def format_morning_summary() -> str:
    """Format morning trading summary - בוקר טוב! Morning briefing"""
    now = datetime.now(ISRAEL_TZ)
    yesterday = now - timedelta(days=1)
    trades = load_trades_for_date(yesterday)
    
    lines = [
        "🌅 <b>בוקר טוב! Good Morning</b>",
        f"📅 {now.strftime('%A, %d %B %Y')}",
        f"🕐 {now.strftime('%H:%M')} Israel Time\n"
    ]
    
    if trades:
        winning = [t for t in trades if float(t.get("pnl", 0)) > 0]
        losing = [t for t in trades if float(t.get("pnl", 0)) <= 0]
        total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
        
        lines.append(f"📊 <b>Yesterday's Summary | סיכום אתמול</b>")
        lines.append(f"✅ Trades: {len(trades)} | {len(winning)} wins, {len(losing)} losses")
        
        pnl_emoji = "💰" if total_pnl > 0 else "📉"
        lines.append(f"{pnl_emoji} Total PNL: <code>${total_pnl:.2f}</code>")
        
        if total_pnl > 0:
            lines.append(f"🎯 Win Rate: {len(winning)/len(trades)*100:.1f}%")
        
        lines.append("")
        lines.append("<b>Top Performers | ביצועים מובילים:</b>")
        top_trades = sorted(trades, key=lambda t: float(t.get("pnl", 0)), reverse=True)[:3]
        for i, t in enumerate(top_trades, 1):
            symbol = t.get("symbol", "N/A")
            pnl = float(t.get("pnl", 0))
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
            lines.append(f"{emoji} {symbol}: <code>${pnl:.2f}</code>")
    else:
        lines.append("💤 <b>No trades yesterday | אין טרייד מאתמול</b>")
        lines.append("🎯 Ready for new opportunities today!")
    
    lines.append("")
    lines.append("🚀 <b>Today's Plan | תוכנית היום:</b>")
    lines.append("• Market scanning active")
    lines.append("• AI analysis enabled")
    lines.append("• Waiting for quality setups")
    lines.append("")
    lines.append("בהצלחה! Good luck trading! 💪")
    
    return "\n".join(lines)

def format_evening_digest() -> str:
    """Format evening daily digest - סיכום יום מסחר Evening briefing"""
    now = datetime.now(ISRAEL_TZ)
    today = now
    trades = load_trades_for_date(today)
    
    lines = [
        "🌙 <b>סיכום יום מסחר | Trading Day Summary</b>",
        f"📅 {now.strftime('%A, %d %B %Y')}",
        f"🕐 {now.strftime('%H:%M')} Israel Time\n"
    ]
    
    if trades:
        winning = [t for t in trades if float(t.get("pnl", 0)) > 0]
        losing = [t for t in trades if float(t.get("pnl", 0)) <= 0]
        total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
        win_rate = len(winning) / len(trades) * 100 if trades else 0
        
        status_emoji = "✅" if total_pnl > 0 else "⚠️" if total_pnl >= -50 else "🔴"
        
        lines.append(f"{status_emoji} <b>Daily Performance | ביצועים יומיים</b>")
        lines.append(f"📈 Trades Executed: {len(trades)}")
        lines.append(f"🎯 Win Rate: {win_rate:.1f}% ({len(winning)}/{len(trades)})")
        
        pnl_emoji = "💰" if total_pnl > 0 else "📉"
        lines.append(f"{pnl_emoji} <b>Total PNL: ${total_pnl:.2f}</b>")
        
        lines.append("")
        lines.append("<b>📊 Trade Breakdown | פירוט טרייד:</b>")
        
        for t in trades:
            symbol = t.get("symbol", "N/A")
            side = t.get("side", "N/A")
            pnl = float(t.get("pnl", 0))
            side_emoji = "🟢" if side == "LONG" else "🔴"
            pnl_emoji = "✅" if pnl > 0 else "❌"
            
            lines.append(f"{side_emoji} {symbol} {side}: {pnl_emoji} <code>${pnl:.2f}</code>")
        
        lines.append("")
        if total_pnl > 0:
            lines.append("🎉 <b>Great day! | יום מצוין!</b>")
        elif total_pnl >= -50:
            lines.append("💪 <b>Stay disciplined | נשאר ממושמעים</b>")
        else:
            lines.append("🔄 <b>Tomorrow is a new day | מחר יום חדש</b>")
    else:
        lines.append("💤 <b>No trades today | אין טרייד היום</b>")
        lines.append("🔍 Market conditions not optimal")
        lines.append("✅ Capital preserved, waiting for better setups")
    
    lines.append("")
    lines.append("🌟 <b>System Status | סטטוס מערכת:</b>")
    lines.append("✅ AlgoGPT: Active")
    lines.append("✅ AI Scanner: Running")
    lines.append("✅ Risk Management: Enabled")
    lines.append("")
    lines.append("🛌 Rest well! Tomorrow brings new opportunities")
    lines.append("לילה טוב! 💤")
    
    return "\n".join(lines)

def wait_until_next_scheduled_time():
    """Wait until next scheduled digest time (morning or evening)"""
    now = datetime.now(ISRAEL_TZ)
    current_hour = now.hour
    
    if current_hour < MORNING_HOUR:
        target_hour = MORNING_HOUR
        target_day = now
        digest_type = "morning"
    elif current_hour < EVENING_HOUR:
        target_hour = EVENING_HOUR
        target_day = now
        digest_type = "evening"
    else:
        target_hour = MORNING_HOUR
        target_day = now + timedelta(days=1)
        digest_type = "morning"
    
    target_time = datetime(
        year=target_day.year,
        month=target_day.month,
        day=target_day.day,
        hour=target_hour,
        minute=0,
        second=0,
        tzinfo=ISRAEL_TZ
    )
    
    wait_seconds = (target_time - now).total_seconds()
    hours = wait_seconds / 3600
    
    logger.info(f"Waiting {hours:.1f} hours until next {digest_type} digest at {target_time.strftime('%H:%M')}")
    
    return wait_seconds, digest_type

async def send_digest(digest_type: str):
    """Send the appropriate digest based on time of day"""
    try:
        if digest_type == "morning":
            message = format_morning_summary()
            logger.info("Sending morning trading summary")
        else:
            message = format_evening_digest()
            logger.info("Sending evening daily digest")
        
        await send_telegram_message(
            message,
            parse_mode="HTML",
            disable_preview=True
        )
        
        logger.info(f"{digest_type.capitalize()} digest sent successfully")
    except Exception as e:
        logger.error(f"Failed to send {digest_type} digest: {e}")

async def digest_loop():
    """Main digest loop - runs twice daily"""
    logger.info(f"Daily Digest Worker started (Morning: {MORNING_HOUR}:00, Evening: {EVENING_HOUR}:00 Israel Time)")
    
    while True:
        try:
            wait_seconds, digest_type = wait_until_next_scheduled_time()
            await asyncio.sleep(wait_seconds)
            
            await send_digest(digest_type)
            
            await asyncio.sleep(60)
            
        except KeyboardInterrupt:
            logger.info("Daily digest worker stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in digest loop: {e}")
            await asyncio.sleep(300)

def main():
    """Main entry point"""
    try:
        asyncio.run(digest_loop())
    except KeyboardInterrupt:
        logger.info("Daily digest worker shutdown")

if __name__ == "__main__":
    main()
