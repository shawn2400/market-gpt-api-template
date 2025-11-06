#!/usr/bin/env python3
# workers/db_keepalive.py
"""
Database Keepalive Worker
=========================
Prevents Neon database auto-pause by executing SELECT 1 every 5 minutes.
Critical for production stability.
"""
import os
import sys
import time
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("db_keepalive")

DB_KEEPALIVE_ENABLE = os.getenv("DB_KEEPALIVE_ENABLE", "1") == "1"
DB_KEEPALIVE_INTERVAL_SEC = int(os.getenv("DB_KEEPALIVE_INTERVAL_SEC", "300"))  # 5 min


async def keepalive_ping():
    """Execute lightweight DB query to keep connection alive"""
    try:
        import psycopg
        from psycopg.rows import dict_row
        
        database_url = os.getenv("DATABASE_URL", "")
        
        if not database_url:
            logger.error("DATABASE_URL not set!")
            return False
        
        start = time.time()
        
        async with await psycopg.AsyncConnection.connect(
            database_url,
            row_factory=dict_row,
            connect_timeout=5
        ) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 AS keepalive")
                result = await cur.fetchone()
        
        latency_ms = (time.time() - start) * 1000
        
        if result and result.get("keepalive") == 1:
            logger.info(f"✅ DB keepalive OK (latency={latency_ms:.1f}ms)")
            return True
        else:
            logger.warning(f"⚠️ DB keepalive unexpected result: {result}")
            return False
    
    except Exception as e:
        logger.error(f"❌ DB keepalive failed: {e}")
        return False


async def main():
    """Main keepalive loop"""
    if not DB_KEEPALIVE_ENABLE:
        logger.info("DB keepalive disabled. Set DB_KEEPALIVE_ENABLE=1 to enable.")
        return
    
    logger.info(f"💓 DB Keepalive started (interval={DB_KEEPALIVE_INTERVAL_SEC}s)")
    
    while True:
        try:
            success = await keepalive_ping()
            
            if not success:
                logger.warning("Keepalive failed, will retry...")
            
            await asyncio.sleep(DB_KEEPALIVE_INTERVAL_SEC)
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Keepalive loop error: {e}")
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
