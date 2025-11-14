#!/usr/bin/env python3
"""
Auto Cleanup Worker - Automated Memory & Storage Management
===========================================================
Automatically cleans up old logs, AI reviews, and improvement files
to prevent disk space issues and keep memory usage optimal.

Cleanup Policies:
- Logs: Delete files older than 7 days
- AI Reviews: Keep latest 100, delete older
- Improvements: Keep last 30 days
- Temporary files: Clean daily

Runs every 6 hours automatically.
"""

import os
import time
import logging
from pathlib import Path
from typing import List
import shutil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("auto_cleanup")

# Configuration from environment
CLEANUP_INTERVAL_SEC = int(os.getenv("CLEANUP_INTERVAL_SEC", "21600"))  # 6 hours default
LOGS_RETENTION_DAYS = int(os.getenv("LOGS_RETENTION_DAYS", "7"))
AI_REVIEWS_KEEP_COUNT = int(os.getenv("AI_REVIEWS_KEEP_COUNT", "100"))
IMPROVEMENTS_RETENTION_DAYS = int(os.getenv("IMPROVEMENTS_RETENTION_DAYS", "30"))
TEMP_FILES_RETENTION_DAYS = int(os.getenv("TEMP_FILES_RETENTION_DAYS", "1"))

# Directories to clean
LOGS_DIR = Path("logs")  # Project logs directory
AI_REVIEWS_DIR = Path("data/ai_reviews")
IMPROVEMENTS_DIR = Path("data/improvements")
LEARNING_DIR = Path("data/learning")
TEMP_DIR = Path("/tmp")


def get_file_age_days(file_path: Path) -> float:
    """Get file age in days"""
    try:
        return (time.time() - file_path.stat().st_mtime) / 86400
    except Exception:
        return 0


def cleanup_old_logs():
    """Delete log files older than LOGS_RETENTION_DAYS"""
    if not LOGS_DIR.exists():
        logger.debug(f"Logs directory doesn't exist: {LOGS_DIR}")
        return
    
    deleted_count = 0
    freed_bytes = 0
    
    try:
        for log_file in LOGS_DIR.glob("*.log"):
            age_days = get_file_age_days(log_file)
            
            if age_days > LOGS_RETENTION_DAYS:
                try:
                    file_size = log_file.stat().st_size
                    log_file.unlink()
                    deleted_count += 1
                    freed_bytes += file_size
                    logger.debug(f"Deleted old log: {log_file.name} (age: {age_days:.1f} days)")
                except Exception as e:
                    logger.error(f"Failed to delete {log_file.name}: {e}")
        
        if deleted_count > 0:
            logger.info(
                f"🧹 Cleaned {deleted_count} old log files, "
                f"freed {freed_bytes / 1024 / 1024:.2f} MB"
            )
    except Exception as e:
        logger.error(f"Log cleanup failed: {e}")


def cleanup_ai_reviews():
    """Keep only the latest AI_REVIEWS_KEEP_COUNT reviews"""
    if not AI_REVIEWS_DIR.exists():
        logger.debug(f"AI reviews directory doesn't exist: {AI_REVIEWS_DIR}")
        return
    
    try:
        review_files = sorted(
            AI_REVIEWS_DIR.glob("*_review.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        deleted_count = 0
        freed_bytes = 0
        
        for review_file in review_files[AI_REVIEWS_KEEP_COUNT:]:
            try:
                file_size = review_file.stat().st_size
                review_file.unlink()
                deleted_count += 1
                freed_bytes += file_size
                logger.debug(f"Deleted old review: {review_file.name}")
            except Exception as e:
                logger.error(f"Failed to delete {review_file.name}: {e}")
        
        if deleted_count > 0:
            logger.info(
                f"🧹 Cleaned {deleted_count} old AI reviews, "
                f"freed {freed_bytes / 1024:.2f} KB"
            )
    except Exception as e:
        logger.error(f"AI reviews cleanup failed: {e}")


def cleanup_improvements():
    """Delete improvement logs older than IMPROVEMENTS_RETENTION_DAYS"""
    if not IMPROVEMENTS_DIR.exists():
        logger.debug(f"Improvements directory doesn't exist: {IMPROVEMENTS_DIR}")
        return
    
    deleted_count = 0
    freed_bytes = 0
    
    try:
        for improvement_file in IMPROVEMENTS_DIR.glob("proposals_*.json"):
            age_days = get_file_age_days(improvement_file)
            
            if age_days > IMPROVEMENTS_RETENTION_DAYS:
                try:
                    file_size = improvement_file.stat().st_size
                    improvement_file.unlink()
                    deleted_count += 1
                    freed_bytes += file_size
                    logger.debug(f"Deleted old improvement: {improvement_file.name}")
                except Exception as e:
                    logger.error(f"Failed to delete {improvement_file.name}: {e}")
        
        if deleted_count > 0:
            logger.info(
                f"🧹 Cleaned {deleted_count} old improvement logs, "
                f"freed {freed_bytes / 1024:.2f} KB"
            )
    except Exception as e:
        logger.error(f"Improvements cleanup failed: {e}")


def cleanup_learning_data():
    """Clean up old shadow logs and bandit state"""
    if not LEARNING_DIR.exists():
        logger.debug(f"Learning directory doesn't exist: {LEARNING_DIR}")
        return
    
    deleted_count = 0
    freed_bytes = 0
    
    try:
        # Clean shadow logs older than 30 days
        for shadow_file in LEARNING_DIR.glob("shadow_*.jsonl"):
            age_days = get_file_age_days(shadow_file)
            
            if age_days > 30:
                try:
                    file_size = shadow_file.stat().st_size
                    shadow_file.unlink()
                    deleted_count += 1
                    freed_bytes += file_size
                except Exception as e:
                    logger.error(f"Failed to delete {shadow_file.name}: {e}")
        
        if deleted_count > 0:
            logger.info(
                f"🧹 Cleaned {deleted_count} old learning files, "
                f"freed {freed_bytes / 1024:.2f} KB"
            )
    except Exception as e:
        logger.error(f"Learning data cleanup failed: {e}")


def cleanup_temp_files():
    """Clean up temporary files"""
    deleted_count = 0
    freed_bytes = 0
    
    try:
        # Clean .tmp files
        for tmp_file in TEMP_DIR.glob("*.tmp"):
            age_days = get_file_age_days(tmp_file)
            
            if age_days > TEMP_FILES_RETENTION_DAYS:
                try:
                    file_size = tmp_file.stat().st_size
                    tmp_file.unlink()
                    deleted_count += 1
                    freed_bytes += file_size
                except Exception as e:
                    logger.debug(f"Failed to delete temp file: {e}")
        
        if deleted_count > 0:
            logger.info(
                f"🧹 Cleaned {deleted_count} temp files, "
                f"freed {freed_bytes / 1024 / 1024:.2f} MB"
            )
    except Exception as e:
        logger.error(f"Temp files cleanup failed: {e}")


def get_disk_usage() -> dict:
    """Get current disk usage statistics"""
    try:
        total, used, free = shutil.disk_usage("/")
        return {
            "total_gb": total / (1024 ** 3),
            "used_gb": used / (1024 ** 3),
            "free_gb": free / (1024 ** 3),
            "used_pct": (used / total) * 100
        }
    except Exception as e:
        logger.error(f"Failed to get disk usage: {e}")
        return {}


def cleanup_blacklist_and_redis():
    """
    Smart Blacklist & Redis cleanup with BlacklistForgivenessManager.
    
    Now runs AUTOMATIC FORGIVENESS for TOP 50 symbols:
    - Removes TOP 50 symbols from blacklist
    - Reduces failure counters by 50% (preserves history)
    - Enforces 1h cool-off for repeat offenders (≥6 failures)
    - Atomic operations to prevent race conditions
    """
    try:
        from utils.blacklist_forgiveness_manager import get_forgiveness_manager
        from utils.redis_client import get_redis
        
        redis_client = get_redis()
        if not redis_client:
            logger.debug("Redis unavailable, skipping blacklist cleanup")
            return
        
        logger.info("🧹 Blacklist & Redis cleanup with auto-forgiveness...")
        
        # 🎯 NEW: Run BlacklistForgivenessManager (auto-forgiveness for TOP 50)
        forgiveness_manager = get_forgiveness_manager()
        if forgiveness_manager:
            try:
                result = forgiveness_manager.run_forgiveness_cycle()
                
                if result.get('status') == 'success':
                    forgiven = result.get('forgiven', 0)
                    cooloff = result.get('cooloff', 0)
                    
                    if forgiven > 0 or cooloff > 0:
                        logger.info(
                            f"✅ Forgiveness cycle: {forgiven} forgiven, "
                            f"{cooloff} on cooloff"
                        )
                elif result.get('status') == 'skipped':
                    logger.debug(f"⚠️ Forgiveness skipped: {result.get('reason')}")
                    
            except Exception as e:
                logger.warning(f"Forgiveness manager failed: {e}")
        
        # 🧹 LEGACY: Orphaned failure counter cleanup (TTL enforcement)
        pattern = "failures:count:*"
        orphaned = 0
        for key in redis_client.scan_iter(match=pattern, count=100):
            ttl = redis_client.ttl(key)
            if ttl == -1:  # No expiry set
                redis_client.expire(key, 7 * 86400)  # 7 days
                orphaned += 1
        
        if orphaned > 0:
            logger.info(f"🧹 Set 7-day expiry on {orphaned} orphaned failure counters")
    
    except Exception as e:
        logger.error(f"Blacklist cleanup failed: {e}", exc_info=True)


def cleanup_dangling_orders():
    """
    🧹 Cleanup dangling Binance orders for closed positions.
    
    Scans ALL open futures orders and cancels any that don't match active positions.
    Also cleans up stale Redis entry_timestamps for closed trades.
    """
    try:
        from utils.binance_client import get_open_orders, get_open_positions, futures_cancel_order
        from utils.redis_client import get_redis
        
        # Get active positions
        positions = get_open_positions() or []
        active_symbols = {p.get("symbol") for p in positions if abs(float(p.get("positionAmt", 0))) > 0}
        
        logger.debug(f"Active positions: {len(active_symbols)} symbols")
        
        # Get ALL open orders (not scoped to any symbol)
        cancelled_count = 0
        try:
            all_orders = get_open_orders() or []  # No symbol = all orders
            logger.debug(f"Checking {len(all_orders)} total open orders")
            
            for order in all_orders:
                order_symbol = order.get("symbol")
                order_id = order.get("orderId")
                
                # Cancel order if symbol not in active positions
                if order_symbol and order_symbol not in active_symbols:
                    try:
                        futures_cancel_order(symbol=order_symbol, order_id=order_id)
                        cancelled_count += 1
                        logger.info(f"🧹 Cancelled dangling order: {order_symbol} #{order_id}")
                    except Exception as e:
                        logger.debug(f"Failed to cancel order {order_id}: {e}")
        except Exception as e:
            logger.error(f"Error fetching/cancelling orders: {e}")
        
        # Cleanup stale Redis entry_timestamps (ALWAYS run, even if no positions)
        redis_client = get_redis()
        if redis_client:
            try:
                cleaned_timestamps = 0
                for key in redis_client.scan_iter(match="entry_timestamp:*", count=100):
                    symbol = key.split(":")[-1] if ":" in key else None
                    
                    # Delete if symbol not in active positions (or if no active positions at all)
                    if symbol and (not active_symbols or symbol not in active_symbols):
                        redis_client.delete(key)
                        cleaned_timestamps += 1
                        logger.debug(f"🧹 Deleted stale entry_timestamp: {key}")
                
                if cleaned_timestamps > 0:
                    logger.info(f"🧹 Cleaned {cleaned_timestamps} stale entry_timestamps from Redis")
            except Exception as e:
                logger.debug(f"Redis cleanup failed: {e}")
        
        if cancelled_count > 0:
            logger.info(f"✅ Dangling orders cleanup: cancelled {cancelled_count} orders")
        else:
            logger.debug("No dangling orders found")
    
    except Exception as e:
        logger.error(f"Dangling orders cleanup failed: {e}")

def run_cleanup():
    """Run full cleanup cycle"""
    logger.info("🧹 Starting auto-cleanup cycle...")
    
    disk_before = get_disk_usage()
    if disk_before:
        logger.info(
            f"📊 Disk before: {disk_before['used_gb']:.2f}GB used "
            f"({disk_before['used_pct']:.1f}%), "
            f"{disk_before['free_gb']:.2f}GB free"
        )
    
    cleanup_old_logs()
    cleanup_ai_reviews()
    cleanup_improvements()
    cleanup_learning_data()
    cleanup_temp_files()
    cleanup_blacklist_and_redis()
    cleanup_dangling_orders()
    
    disk_after = get_disk_usage()
    if disk_before and disk_after:
        freed_gb = disk_before['used_gb'] - disk_after['used_gb']
        logger.info(
            f"✅ Cleanup complete! Freed {freed_gb:.3f}GB, "
            f"{disk_after['free_gb']:.2f}GB now free "
            f"({disk_after['used_pct']:.1f}% used)"
        )
    else:
        logger.info("✅ Cleanup complete!")


def main():
    """Main loop - runs cleanup every CLEANUP_INTERVAL_SEC"""
    logger.info(f"🚀 Auto Cleanup Worker started")
    logger.info(f"📋 Configuration:")
    logger.info(f"  - Cleanup interval: {CLEANUP_INTERVAL_SEC}s ({CLEANUP_INTERVAL_SEC//3600}h)")
    logger.info(f"  - Logs retention: {LOGS_RETENTION_DAYS} days")
    logger.info(f"  - AI reviews keep: {AI_REVIEWS_KEEP_COUNT} latest")
    logger.info(f"  - Improvements retention: {IMPROVEMENTS_RETENTION_DAYS} days")
    logger.info(f"  - Temp files retention: {TEMP_FILES_RETENTION_DAYS} days")
    
    while True:
        try:
            run_cleanup()
        except Exception as e:
            logger.error(f"Cleanup cycle failed: {e}", exc_info=True)
        
        logger.info(f"⏰ Next cleanup in {CLEANUP_INTERVAL_SEC//3600}h...")
        time.sleep(CLEANUP_INTERVAL_SEC)


if __name__ == "__main__":
    main()
