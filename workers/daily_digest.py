#!/usr/bin/env python3
# workers/daily_digest.py
"""
Worker שרץ פעם ביום בחצות (שעון ישראל) ושולח דוח יומי
"""
import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.trade_reports import send_daily_digest_telegram, ISRAEL_TZ

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("daily_digest")

TRADES_LOG_PATH = os.getenv("TRADES_LOG_PATH", "data/trades_log.json")

def load_trades_for_date(date: datetime) -> list:
    """
    טוען טרייד שנסגרו בתאריך מסוים
    """
    try:
        if not Path(TRADES_LOG_PATH).exists():
            return []
        
        with open(TRADES_LOG_PATH, 'r') as f:
            all_trades = json.load(f)
        
        # Filter trades from the specific date
        date_str = date.strftime("%Y-%m-%d")
        day_trades = []
        
        for trade in all_trades:
            # Check if trade was closed on this date
            closed_at = trade.get("closed_at") or trade.get("updated_at")
            if closed_at and date_str in closed_at:
                day_trades.append(trade)
        
        return day_trades
    
    except Exception as e:
        logger.error(f"Failed to load trades: {e}")
        return []

def wait_until_midnight():
    """
    ממתין עד חצות הלילה (שעון ישראל)
    """
    now = datetime.now(ISRAEL_TZ)
    tomorrow = now + timedelta(days=1)
    midnight = datetime(
        year=tomorrow.year,
        month=tomorrow.month,
        day=tomorrow.day,
        hour=0,
        minute=0,
        second=0,
        tzinfo=ISRAEL_TZ
    )
    
    wait_seconds = (midnight - now).total_seconds()
    logger.info(f"Waiting {wait_seconds/3600:.1f} hours until midnight (Israel time)")
    
    return wait_seconds

def run_daily_digest():
    """
    Main loop - רץ אחת ביום בחצות
    """
    logger.info("Daily Digest Worker started")
    
    while True:
        try:
            # Wait until midnight
            wait_seconds = wait_until_midnight()
            time.sleep(wait_seconds)
            
            # It's now midnight - generate report for yesterday
            now = datetime.now(ISRAEL_TZ)
            yesterday = now - timedelta(days=1)
            
            logger.info(f"Generating daily digest for {yesterday.strftime('%Y-%m-%d')}")
            
            # Load yesterday's trades
            trades = load_trades_for_date(yesterday)
            
            if trades:
                send_daily_digest_telegram(trades)
                logger.info(f"Daily digest sent: {len(trades)} trades")
            else:
                logger.info("No trades to report for yesterday")
            
            # Sleep a bit to avoid double-triggering
            time.sleep(60)
        
        except KeyboardInterrupt:
            logger.info("Daily digest worker stopped by user")
            break
        
        except Exception as e:
            logger.error(f"Error in daily digest loop: {e}")
            time.sleep(300)  # Wait 5 minutes before retrying

if __name__ == "__main__":
    run_daily_digest()
