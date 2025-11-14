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
    """Smart Blacklist & Redis cleanup"""
    try:
        from utils.redis_client import get_redis
        import json
        
        redis_client = get_redis()
        if not redis_client:
            logger.debug("Redis unavailable, skipping blacklist cleanup")
            return
        
        logger.info("🧹 Blacklist & Redis cleanup...")
        
        temp_blacklist_key = "blacklist:temp"
        temp_data = redis_client.get(temp_blacklist_key)
        
        if temp_data:
            blacklist = json.loads(temp_data)
            original_count = len(blacklist)
            
            cutoff = time.time() - (24 * 3600)
            blacklist = [
                entry for entry in blacklist
                if entry.get("timestamp", 0) > cutoff
            ]
            
            if len(blacklist) < original_count:
                redis_client.setex(
                    temp_blacklist_key,
                    86400,
                    json.dumps(blacklist)
                )
                logger.info(
                    f"🧹 Cleaned {original_count - len(blacklist)} stale blacklist entries"
                )
        
        top_50_key = "top50:approved_list"
        top_50_data = redis_client.get(top_50_key)
        
        if top_50_data:
            top_50_symbols = json.loads(top_50_data)
            reset_count = 0
            
            for symbol in top_50_symbols:
                failure_key = f"failures:count:{symbol}"
                if redis_client.exists(failure_key):
                    redis_client.delete(failure_key)
                    reset_count += 1
            
            if reset_count > 0:
                logger.info(f"🧹 Reset {reset_count} failure counters (now in TOP 50)")
        
        pattern = "failures:count:*"
        orphaned = 0
        for key in redis_client.scan_iter(match=pattern, count=100):
            ttl = redis_client.ttl(key)
            if ttl == -1:
                redis_client.expire(key, 7 * 86400)
                orphaned += 1
        
        if orphaned > 0:
            logger.info(f"🧹 Set expiry on {orphaned} orphaned failure counters")
    
    except Exception as e:
        logger.error(f"Blacklist cleanup failed: {e}")


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
