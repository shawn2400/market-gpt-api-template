# utils/auto_repair.py
"""
🛠️ Auto-Repair System - Fixed version (4 bugs resolved)
Automatically detects and fixes common system issues
"""
import os
import logging
import asyncio
import httpx
from typing import Dict, Any, List, Optional

logger = logging.getLogger("algogpt.auto_repair")

# Configuration
ENABLED = os.getenv("AUTO_REPAIR_ENABLE", "0").lower() in ("1", "true", "yes")
CHECK_INTERVAL = int(os.getenv("AUTO_REPAIR_INTERVAL", "60"))
MAX_ATTEMPTS = int(os.getenv("AUTO_REPAIR_MAX_ATTEMPTS", "3"))

# Global state
_loop_running = False
_repair_attempts: Dict[str, int] = {}
_backoff_delays = [1, 2, 5, 10, 30]  # Exponential backoff

# API endpoint
API_BASE = os.getenv("PUBLIC_HOST", "http://localhost:5000")


async def detect_problems() -> List[str]:
    """
    Detect system problems that HAVE repair handlers
    FIX: Only return issues we can actually fix
    
    Returns:
        List of problem identifiers that can be repaired
    """
    problems = []
    
    try:
        # Check Redis connectivity
        from utils.redis_client import get_redis
        try:
            r = get_redis()
            r.ping()
        except Exception as e:
            logger.warning(f"Redis problem detected: {e}")
            problems.append("redis")
    
    except Exception as e:
        logger.error(f"Failed to check Redis: {e}")
    
    try:
        # Check Binance client health
        from utils.binance_client import get_binance_client
        try:
            client = get_binance_client()
            # Simple connectivity check
            if client:
                pass  # Client exists
            else:
                problems.append("binance")
        except Exception as e:
            logger.warning(f"Binance problem detected: {e}")
            problems.append("binance")
    
    except Exception as e:
        logger.error(f"Failed to check Binance: {e}")
    
    try:
        # Check WebSocket (if enabled)
        if os.getenv("USER_STREAM_ENABLE", "0") == "1":
            from utils import ws_user_stream
            status = ws_user_stream.status()
            if not status.get("running", False):
                problems.append("userstream")
    
    except Exception as e:
        logger.error(f"Failed to check WebSocket: {e}")
    
    # NOTE: We do NOT check /readyz, /version, /status endpoints
    # because they don't have repair handlers!
    
    return problems


async def repair_issue(problem: str) -> bool:
    """
    Attempt to repair a specific issue
    FIX: All operations are async, no blocking I/O
    
    Args:
        problem: Problem identifier
        
    Returns:
        True if repaired successfully
    """
    # Track attempts
    if problem not in _repair_attempts:
        _repair_attempts[problem] = 0
    
    _repair_attempts[problem] += 1
    attempt = _repair_attempts[problem]
    
    if attempt > MAX_ATTEMPTS:
        logger.error(f"Max repair attempts ({MAX_ATTEMPTS}) exceeded for {problem}")
        return False
    
    # Exponential backoff before retry
    if attempt > 1:
        delay_idx = min(attempt - 1, len(_backoff_delays) - 1)
        delay = _backoff_delays[delay_idx]
        logger.info(f"Waiting {delay}s before repair attempt {attempt}/{MAX_ATTEMPTS}")
        await asyncio.sleep(delay)
    
    logger.info(f"🛠️ Repairing {problem} (attempt {attempt}/{MAX_ATTEMPTS})")
    
    try:
        if problem == "redis":
            # FIX: Async Redis reconnect
            from utils.redis_client import redis_reconnect
            success = await redis_reconnect()
            if success:
                logger.info(f"✅ Redis repaired")
                _repair_attempts[problem] = 0
                return True
        
        elif problem == "binance":
            # FIX: Async Binance reload
            from utils.binance_client import reload_binance_clients
            success = await reload_binance_clients()
            if success:
                logger.info(f"✅ Binance repaired")
                _repair_attempts[problem] = 0
                return True
        
        elif problem == "userstream":
            # Restart WebSocket
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(f"{API_BASE}/system/ws-restart")
                    if r.status_code == 200:
                        logger.info(f"✅ UserStream repaired")
                        _repair_attempts[problem] = 0
                        return True
            except Exception as e:
                logger.error(f"Failed to restart UserStream: {e}")
        
        else:
            logger.warning(f"Unknown problem type: {problem}")
    
    except Exception as e:
        logger.error(f"Failed to repair {problem}: {e}", exc_info=True)
    
    return False


async def auto_repair_loop():
    """
    Main auto-repair loop
    FIX: Singleton pattern - only one loop can run
    """
    global _loop_running
    
    if not ENABLED:
        logger.info("Auto-Repair disabled (set AUTO_REPAIR_ENABLE=1 to enable)")
        return
    
    # FIX: Singleton enforcement
    if _loop_running:
        logger.warning("Auto-Repair loop already running!")
        return
    
    _loop_running = True
    logger.info(f"🛠️ Starting Auto-Repair loop (interval={CHECK_INTERVAL}s)")
    
    # Wait for startup
    await asyncio.sleep(30)
    
    while True:
        try:
            # Detect problems
            problems = await detect_problems()
            
            if problems:
                logger.info(f"Problems detected: {problems}")
                
                # Attempt repairs
                for problem in problems:
                    success = await repair_issue(problem)
                    
                    if success:
                        # Notify Telegram
                        try:
                            from utils.telegram_notifier import notify_info
                            await notify_info(
                                f"🛠️ Auto-Repair Success\n"
                                f"Fixed: {problem}\n"
                                f"System: operational"
                            )
                        except Exception:
                            pass
                    else:
                        # If repair failed too many times, trigger circuit breaker
                        if _repair_attempts.get(problem, 0) >= MAX_ATTEMPTS:
                            logger.critical(f"Circuit breaker triggered for {problem}")
                            
                            # Freeze stage engine
                            try:
                                from utils import stage_engine
                                stage_engine.freeze_stage(
                                    f"Auto-Repair failed for {problem} after {MAX_ATTEMPTS} attempts"
                                )
                            except Exception as e:
                                logger.error(f"Failed to trigger freeze: {e}")
                            
                            # Notify Telegram
                            try:
                                from utils.telegram_notifier import notify_error
                                await notify_error(
                                    f"🚨 Auto-Repair FAILED\n"
                                    f"Issue: {problem}\n"
                                    f"Attempts: {MAX_ATTEMPTS}\n"
                                    f"Action: System frozen\n"
                                    f"Manual intervention required"
                                )
                            except Exception:
                                pass
            
        except Exception as e:
            logger.error(f"Auto-repair loop error: {e}", exc_info=True)
        
        # Sleep until next check
        await asyncio.sleep(CHECK_INTERVAL)


def is_running() -> bool:
    """Check if auto-repair loop is running"""
    return _loop_running
