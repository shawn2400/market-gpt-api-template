#!/usr/bin/env python3
# utils/digest_scheduler.py
"""
Digest Scheduler - Israeli Timezone
==================================
Schedules digest sends at specific times:
- Health: 08:00, 16:00, 00:00 Israel time
- Trade/PNL: Every 30 minutes
"""
import os
import logging
import asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Callable

logger = logging.getLogger("algogpt.digest_scheduler")

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

HEALTH_DIGEST_TIMES = [
    time(8, 0),   # 08:00
    time(16, 0),  # 16:00
    time(0, 0),   # 00:00
]

TRADE_DIGEST_INTERVAL_SEC = int(os.getenv("TRADE_DIGEST_INTERVAL_SEC", "1800"))  # 30 min


class DigestScheduler:
    """Schedules digest sends"""
    
    def __init__(self, health_callback: Callable, trade_callback: Callable):
        self.health_callback = health_callback
        self.trade_callback = trade_callback
        self.running = False
    
    async def start(self):
        """Start scheduler loops"""
        self.running = True
        logger.info("Digest scheduler started")
        
        await asyncio.gather(
            self._health_loop(),
            self._trade_loop()
        )
    
    def stop(self):
        """Stop scheduler"""
        self.running = False
        logger.info("Digest scheduler stopped")
    
    async def _health_loop(self):
        """Schedule health digests at specific times (Israel timezone)"""
        while self.running:
            try:
                now = datetime.now(ISRAEL_TZ)
                current_time = now.time()
                
                next_digest_time = None
                for digest_time in sorted(HEALTH_DIGEST_TIMES):
                    if current_time < digest_time:
                        next_digest_time = digest_time
                        break
                
                if next_digest_time is None:
                    next_digest_time = HEALTH_DIGEST_TIMES[0]
                    target_datetime = datetime.combine(now.date(), next_digest_time, tzinfo=ISRAEL_TZ)
                    from datetime import timedelta
                    target_datetime += timedelta(days=1)
                else:
                    target_datetime = datetime.combine(now.date(), next_digest_time, tzinfo=ISRAEL_TZ)
                
                sleep_seconds = (target_datetime - now).total_seconds()
                
                if sleep_seconds > 0:
                    logger.info(f"Next health digest at {target_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')} (in {int(sleep_seconds/60)} min)")
                    await asyncio.sleep(sleep_seconds)
                
                logger.info(f"Sending scheduled health digest at {datetime.now(ISRAEL_TZ).strftime('%H:%M:%S')}")
                await self.health_callback()
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Health loop error: {e}")
                await asyncio.sleep(300)
    
    async def _trade_loop(self):
        """Schedule trade digests every 30 minutes"""
        while self.running:
            try:
                await asyncio.sleep(TRADE_DIGEST_INTERVAL_SEC)
                
                logger.info(f"Sending scheduled trade digest at {datetime.now(ISRAEL_TZ).strftime('%H:%M:%S')}")
                await self.trade_callback()
                
            except Exception as e:
                logger.error(f"Trade loop error: {e}")
                await asyncio.sleep(300)
