#!/usr/bin/env python3
"""
Immediate Blacklist Flush Script
================================
Emergency script to immediately clear TEMP BLACKLIST and failure counters
Run this when blacklist is blocking all trades

Usage:
    python scripts/immediate_blacklist_flush.py
"""

import sys
import os
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.redis_client import get_redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("immediate_flush")


def immediate_blacklist_flush():
    """ניקוי מיידי של TEMP BLACKLIST - הרצה עכשיו!"""
    
    logger.info("🚨 Starting IMMEDIATE BLACKLIST FLUSH")
    
    try:
        redis_client = get_redis()
        if not redis_client:
            logger.error("❌ Redis not available!")
            return {'status': 'ERROR', 'error': 'Redis unavailable'}
        
        # Test Redis connection
        redis_client.ping()
        logger.info("✅ Redis connection OK")
        
        # 1. קבלת כל הסימבולים ב-TEMP BLACKLIST
        temp_blacklist_key = "blacklist:temp"
        blacklist_data = redis_client.get(temp_blacklist_key)
        
        blacklisted_symbols = []
        if blacklist_data:
            try:
                blacklist = json.loads(blacklist_data)
                blacklisted_symbols = [entry['symbol'] for entry in blacklist]
                logger.info(f"🔍 Found {len(blacklisted_symbols)} symbols in TEMP BLACKLIST")
            except Exception as e:
                logger.warning(f"Failed to parse blacklist: {e}")
        else:
            logger.info("📊 TEMP BLACKLIST is empty")
        
        # 2. ניקוי TEMP BLACKLIST
        if blacklisted_symbols:
            redis_client.delete(temp_blacklist_key)
            logger.info(f"✅ Cleared TEMP BLACKLIST: {len(blacklisted_symbols)} symbols removed")
            logger.info(f"   Symbols: {', '.join(blacklisted_symbols[:10])}{'...' if len(blacklisted_symbols) > 10 else ''}")
        
        # 3. איפוס failure counts
        failure_pattern = "failures:count:*"
        failure_keys = []
        for key in redis_client.scan_iter(match=failure_pattern, count=100):
            failure_keys.append(key)
        
        deleted_failures = 0
        for key in failure_keys:
            redis_client.delete(key)
            deleted_failures += 1
            
        logger.info(f"✅ Cleared {deleted_failures} failure counts")
        
        # 4. איפוס failure history (if exists)
        history_pattern = "failures:history:*"
        history_keys = []
        for key in redis_client.scan_iter(match=history_pattern, count=100):
            history_keys.append(key)
        
        deleted_history = 0
        for key in history_keys:
            redis_client.delete(key)
            deleted_history += 1
            
        if deleted_history > 0:
            logger.info(f"✅ Cleared {deleted_history} failure histories")
        
        # 5. יצירת דוח
        report = {
            'timestamp': datetime.now().isoformat(),
            'cleaned_blacklist_count': len(blacklisted_symbols),
            'cleaned_symbols': blacklisted_symbols,
            'cleaned_failure_counts': deleted_failures,
            'cleaned_histories': deleted_history,
            'status': 'SUCCESS'
        }
        
        # שמירת דוח הניקוי (24h TTL)
        redis_client.setex(
            "cleanup:immediate_flush_report",
            86400,
            json.dumps(report)
        )
        
        logger.info("=" * 60)
        logger.info("🎉 IMMEDIATE BLACKLIST FLUSH COMPLETED!")
        logger.info("=" * 60)
        logger.info(f"📊 Blacklist entries removed: {len(blacklisted_symbols)}")
        logger.info(f"📊 Failure counters reset: {deleted_failures}")
        logger.info(f"📊 Failure histories cleared: {deleted_history}")
        logger.info("=" * 60)
        logger.info("🚀 System ready for trading - blacklist cleared!")
        logger.info("=" * 60)
        
        return report
        
    except Exception as e:
        logger.error(f"❌ Immediate flush failed: {e}", exc_info=True)
        return {'status': 'ERROR', 'error': str(e)}


if __name__ == "__main__":
    result = immediate_blacklist_flush()
    
    if result.get('status') == 'SUCCESS':
        sys.exit(0)
    else:
        sys.exit(1)
