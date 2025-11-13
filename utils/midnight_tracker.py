#!/usr/bin/env python3
# utils/midnight_tracker.py
"""
Midnight Tracker - Ensures daily summary sent only ONCE at 00:00 Israel time
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

TRACKER_FILE = Path("data/last_midnight_summary.txt")

def should_send_midnight_summary() -> bool:
    """
    Check if we should send midnight summary.
    Returns True only ONCE per day at 00:00 Israel time.
    """
    israel_tz = ZoneInfo("Asia/Jerusalem")
    israel_time = datetime.now(israel_tz)
    
    # Only check during midnight hour (00:00-00:59)
    if israel_time.hour != 0:
        return False
    
    # Get current date in Israel timezone
    today = israel_time.date().isoformat()
    
    # Check if we already sent today
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if TRACKER_FILE.exists():
        last_sent = TRACKER_FILE.read_text().strip()
        if last_sent == today:
            return False  # Already sent today
    
    # Mark as sent
    TRACKER_FILE.write_text(today)
    return True

