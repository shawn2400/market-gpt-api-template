# watchers/stage_watcher.py
"""
🎯 Stage Watcher - Background monitor for Stage Engine
Runs every 60 seconds to check system health and manage stage transitions
"""
import os
import logging
import asyncio
from utils import stage_controller

logger = logging.getLogger("algogpt.stage_watcher")

# Configuration
ENABLED = os.getenv("STAGE_ENGINE_ENABLE", "1").lower() in ("1", "true", "yes")
CHECK_INTERVAL = int(os.getenv("STAGE_HEALTH_INTERVAL", "60"))  # seconds

# State
_watcher_running = False


async def start_stage_watcher():
    """
    Start the stage watcher loop
    Runs indefinitely in background
    """
    global _watcher_running
    
    if not ENABLED:
        logger.info("Stage Engine disabled (set STAGE_ENGINE_ENABLE=1 to enable)")
        return
    
    if _watcher_running:
        logger.warning("Stage watcher already running!")
        return
    
    _watcher_running = True
    logger.info(f"🎯 Starting Stage Watcher (interval={CHECK_INTERVAL}s)")
    
    # Wait for startup to complete
    await asyncio.sleep(30)
    
    while True:
        try:
            # Run stage tick (evaluate health, take action)
            # FIX: stage_tick() is now async
            result = await stage_controller.stage_tick()
            
            # Log action if taken
            if result.get("action_taken"):
                action = result["action_taken"]
                logger.info(f"Stage action: {action}")
            
            # Every 10 checks (10 minutes), send Telegram report
            if hasattr(start_stage_watcher, "_tick_count"):
                start_stage_watcher._tick_count += 1
            else:
                start_stage_watcher._tick_count = 1
            
            if start_stage_watcher._tick_count % 10 == 0:
                # FIX: send_stage_report_telegram() is now async
                await stage_controller.send_stage_report_telegram()
            
        except Exception as e:
            logger.error(f"Stage watcher error: {e}", exc_info=True)
        
        # Sleep until next check
        await asyncio.sleep(CHECK_INTERVAL)


def is_running() -> bool:
    """Check if stage watcher is running"""
    return _watcher_running
