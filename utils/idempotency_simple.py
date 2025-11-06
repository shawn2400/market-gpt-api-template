# -*- coding: utf-8 -*-
"""
Simple Idempotency Manager (Memory-based)
HMAC-based duplicate order prevention with time-window buckets.
Used for dynamic trading to prevent duplicate SL/TP updates.
"""
import time
import hashlib
import hmac
import os
import logging

log = logging.getLogger(__name__)

WINDOW_SEC = int(os.getenv("IDEMP_WINDOW_SEC", "90"))
SECRET = os.getenv("IDEMP_SECRET", "demo_secret_change_in_production")

# Cache structure: {bucket_timestamp: set(keys)}
_cache = {}


def make_key(route: str, payload: str) -> str:
    """
    Generate HMAC key for route + payload + time bucket.
    
    Args:
        route: Operation identifier (e.g., "manage_dyn", "sl_update")
        payload: JSON string of order parameters
        
    Returns:
        HMAC SHA256 hex digest
    """
    bucket = int(time.time() / WINDOW_SEC)
    msg = f"{route}|{payload}|{bucket}".encode()
    return hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()


def seen(key: str) -> bool:
    """
    Check if key has been seen in current time window.
    Also performs cleanup of old buckets.
    
    Args:
        key: HMAC key to check
        
    Returns:
        True if key was already seen (duplicate), False if new
    """
    global _cache
    
    current_bucket = int(time.time() / WINDOW_SEC)
    
    # Initialize current bucket if needed
    _cache.setdefault(current_bucket, set())
    
    # Cleanup old buckets (keep only current and previous 2)
    for old_bucket in list(_cache.keys()):
        if old_bucket < current_bucket - 2:
            _cache.pop(old_bucket, None)
            log.debug(f"[IdempotencySimple] Cleaned old bucket: {old_bucket}")
    
    # Check if key exists in current bucket
    if key in _cache[current_bucket]:
        log.warning(f"[IdempotencySimple] Duplicate detected: {key[:16]}...")
        return True
    
    # Mark as seen
    _cache[current_bucket].add(key)
    log.debug(f"[IdempotencySimple] New key registered: {key[:16]}...")
    return False
