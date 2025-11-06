#!/usr/bin/env python3
# workers/telegram_digest_reporter.py
"""
Telegram Digest Reporter Worker
==============================
Sends consolidated Telegram reports on schedule:
- Health: 08:00, 16:00, 00:00 Israel time
- Trade/PNL: Every 30 minutes (only if SL/TP hits)
"""
import os
import sys
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.telegram_digest import send_health_digest, send_trade_digest
from utils.digest_scheduler import DigestScheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("telegram_digest_reporter")


async def main():
    """Main worker loop"""
    logger.info("📊 Telegram Digest Reporter started")
    
    scheduler = DigestScheduler(
        health_callback=send_health_digest,
        trade_callback=send_trade_digest
    )
    
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.stop()
    except Exception as e:
        logger.error(f"Worker error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
