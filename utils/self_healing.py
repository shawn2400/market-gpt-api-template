# utils/self_healing.py
"""
🔥 Self-Healing System - Fixed version (non-aggressive, with backoff)
Monitors overall system availability and triggers recovery if system becomes unreachable
"""
import os
import logging
import asyncio
from typing import Optional

logger = logging.getLogger("algogpt.self_healing")

# Configuration
ENABLED = os.getenv("SELF_HEALING_ENABLE", "0").lower() in ("1", "true", "yes")
COOLDOWN = int(os.getenv("SELF_HEALING_COOLDOWN", "300"))  # 5 minutes between checks
MAX_FAILURES = int(os.getenv("SELF_HEALING_MAX_FAILURES", "5"))  # Must fail 5 times before action

# API endpoint
API_BASE = os.getenv("PUBLIC_HOST", "http://localhost:5000")

# Global state
_loop_running = False
_consecutive_failures = 0
_last_recovery_time = 0
RECOVERY_COOLDOWN = 1800  # 30 minutes between recovery attempts


async def self_healing_loop():
    """
    Main self-healing monitoring loop
    FIX: Non-aggressive, with proper backoff and cooldown
    """
    global _loop_running, _consecutive_failures, _last_recovery_time
    
    if not ENABLED:
        logger.info("Self-Healing disabled (set SELF_HEALING_ENABLE=1 to enable)")
        return
    
    # FIX: Singleton enforcement
    if _loop_running:
        logger.warning("Self-Healing loop already running!")
        return
    
    _loop_running = True
    logger.info(f"🔥 Starting Self-Healing loop (cooldown={COOLDOWN}s, max_failures={MAX_FAILURES})")
    
    # Wait for startup
    await asyncio.sleep(60)
    
    import time
    import httpx
    
    while True:
        try:
            # Check if system is responsive
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"{API_BASE}/readyz")
                    
                    if r.status_code == 200:
                        # System healthy
                        if _consecutive_failures > 0:
                            logger.info(f"✅ System recovered after {_consecutive_failures} failures")
                            _consecutive_failures = 0
                            
                            # Notify recovery
                            try:
                                from utils.telegram_notifier import notify_info
                                await notify_info(
                                    f"✅ Self-Healing: System recovered\n"
                                    f"System is now responsive"
                                )
                            except Exception:
                                pass
                    else:
                        # Unexpected status code
                        _consecutive_failures += 1
                        logger.warning(
                            f"⚠️ Self-Healing: /readyz returned {r.status_code} "
                            f"(failure {_consecutive_failures}/{MAX_FAILURES})"
                        )
            
            except Exception as e:
                _consecutive_failures += 1
                logger.warning(
                    f"⚠️ Self-Healing: System unreachable - {e} "
                    f"(failure {_consecutive_failures}/{MAX_FAILURES})"
                )
            
            # FIX: Only trigger recovery after MAX_FAILURES consecutive failures
            # AND respect recovery cooldown
            if _consecutive_failures >= MAX_FAILURES:
                current_time = time.time()
                
                # FIX: Backoff - don't trigger recovery too frequently
                if current_time - _last_recovery_time < RECOVERY_COOLDOWN:
                    remaining = RECOVERY_COOLDOWN - (current_time - _last_recovery_time)
                    logger.warning(
                        f"Recovery on cooldown ({remaining:.0f}s remaining), "
                        f"failures: {_consecutive_failures}"
                    )
                else:
                    logger.critical(
                        f"🔥 Self-Healing: {_consecutive_failures} consecutive failures - "
                        f"triggering recovery"
                    )
                    
                    # Freeze stage engine (safer than restart)
                    try:
                        from utils import stage_engine
                        stage_engine.freeze_stage(
                            f"Self-Healing: {_consecutive_failures} consecutive health check failures"
                        )
                        logger.info("✅ Stage Engine frozen as recovery action")
                        _last_recovery_time = current_time
                        _consecutive_failures = 0
                    except Exception as e:
                        logger.error(f"Failed to freeze stage engine: {e}")
                    
                    # Notify critical failure
                    try:
                        from utils.telegram_notifier import notify_error
                        await notify_error(
                            f"🚨 Self-Healing: CRITICAL SYSTEM FAILURE\n"
                            f"Consecutive failures: {_consecutive_failures}\n"
                            f"Action: System frozen\n"
                            f"Please investigate and use /stage_unfreeze to resume"
                        )
                    except Exception:
                        pass
        
        except Exception as e:
            logger.error(f"Self-healing loop error: {e}", exc_info=True)
        
        # FIX: Long cooldown between checks (not too aggressive)
        await asyncio.sleep(COOLDOWN)


def is_running() -> bool:
    """Check if self-healing loop is running"""
    return _loop_running
