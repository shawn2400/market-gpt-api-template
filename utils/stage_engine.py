# utils/stage_engine.py
"""
🎯 Stage Engine - AlgoGPT Production Deployment System
Manages automatic progression through deployment stages: Stage 1 → 2 → 3

Stage 1: Stable-Health (Monitoring only, no trading)
Stage 2: Pre-Trading Validation (Limited workers, health checks)
Stage 3: Full Auto Trading (All systems operational)
"""
import os
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger("algogpt.stage_engine")

# Stage state file (persisted in /tmp for fast access)
STAGE_FILE = "/tmp/algogpt_current_stage.txt"
STAGE_HISTORY_FILE = "/tmp/algogpt_stage_history.txt"

# Stage definitions
STAGES = {
    1: {
        "name": "Stable-Health",
        "description": "Monitoring only, no trading",
        "auto_run": False,
        "enable_auto_trading": False,
        "manage_trades": False,
        "pool_per_cycle": 0,
        "min_uptime_hours": 0.0,
        "promotion_criteria": {
            "uptime_hours": 4.0,
            "max_errors": 5,
            "max_cpu": 80,
            "max_ram": 80,
            "redis_health": "ok",
            "ws_health": "connected"
        }
    },
    2: {
        "name": "Full Auto Trading (Validation)",
        "description": "All systems operational, full automation with monitoring",
        "auto_run": True,
        "enable_auto_trading": True,
        "manage_trades": True,
        "pool_per_cycle": 30,
        "min_uptime_hours": 4.0,
        "promotion_criteria": {
            "uptime_hours": 6.0,
            "max_errors": 3,
            "max_cpu": 75,
            "max_ram": 75,
            "redis_health": "ok",
            "ws_health": "connected",
            "ban_shield_zone": "green"
        }
    },
    3: {
        "name": "Full Auto Trading",
        "description": "All systems operational",
        "auto_run": True,
        "enable_auto_trading": True,
        "manage_trades": True,
        "pool_per_cycle": 50,
        "min_uptime_hours": 10.0,
        "promotion_criteria": None  # Max stage, no promotion
    }
}

# Global state
_current_stage = 1
_stage_start_time = time.time()
_frozen = False
_freeze_reason = ""


def load_current_stage() -> int:
    """Load current stage from file (persistent across restarts)"""
    global _current_stage, _stage_start_time
    
    if os.path.exists(STAGE_FILE):
        try:
            with open(STAGE_FILE, "r") as f:
                data = f.read().strip()
                stage, timestamp = data.split(",")
                _current_stage = int(stage)
                _stage_start_time = float(timestamp)
                logger.info(f"✅ Loaded stage {_current_stage} from file (started at {timestamp})")
        except Exception as e:
            logger.warning(f"Failed to load stage from file: {e}, defaulting to Stage 1")
            _current_stage = 1
            _stage_start_time = time.time()
    else:
        logger.info("No stage file found, starting at Stage 1")
        _current_stage = 1
        _stage_start_time = time.time()
    
    _save_stage()
    return _current_stage


def _save_stage():
    """Save current stage to file"""
    try:
        with open(STAGE_FILE, "w") as f:
            f.write(f"{_current_stage},{_stage_start_time}")
        logger.debug(f"Saved stage {_current_stage} to file")
    except Exception as e:
        logger.error(f"Failed to save stage to file: {e}")


def _log_stage_history(event: str):
    """Log stage transitions to history file"""
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(STAGE_HISTORY_FILE, "a") as f:
            f.write(f"{timestamp} | Stage {_current_stage} | {event}\n")
    except Exception as e:
        logger.error(f"Failed to log stage history: {e}")


def get_current_stage() -> int:
    """Get current stage number"""
    return _current_stage


def get_stage_info(stage: Optional[int] = None) -> Dict[str, Any]:
    """Get information about a stage"""
    if stage is None:
        stage = _current_stage
    
    if stage not in STAGES:
        raise ValueError(f"Invalid stage: {stage}")
    
    return STAGES[stage]


def get_stage_uptime_hours() -> float:
    """Get how long current stage has been running (in hours)"""
    return (time.time() - _stage_start_time) / 3600


def is_frozen() -> bool:
    """Check if system is frozen"""
    return _frozen


def get_freeze_reason() -> str:
    """Get reason for freeze"""
    return _freeze_reason


def freeze_stage(reason: str) -> bool:
    """
    Freeze the system (prevent auto-promotion and disable trading)
    
    Args:
        reason: Reason for freeze
        
    Returns:
        True if frozen successfully
    """
    global _frozen, _freeze_reason
    
    if _frozen:
        logger.warning(f"System already frozen: {_freeze_reason}")
        return False
    
    _frozen = True
    _freeze_reason = reason
    _log_stage_history(f"FROZEN: {reason}")
    logger.warning(f"🥶 System FROZEN: {reason}")
    
    # Send Telegram alert
    try:
        from utils.telegram_notifier import notify_error
        import asyncio
        asyncio.create_task(notify_error(
            f"🥶 AlgoGPT FROZEN\n"
            f"Stage: {_current_stage}\n"
            f"Reason: {reason}\n"
            f"Action: Auto-trading disabled"
        ))
    except Exception as e:
        logger.error(f"Failed to send freeze notification: {e}")
    
    return True


def unfreeze_stage() -> bool:
    """
    Unfreeze the system (resume auto-promotion)
    
    Returns:
        True if unfrozen successfully
    """
    global _frozen, _freeze_reason
    
    if not _frozen:
        logger.warning("System not frozen, nothing to unfreeze")
        return False
    
    old_reason = _freeze_reason
    _frozen = False
    _freeze_reason = ""
    _log_stage_history(f"UNFROZEN (was: {old_reason})")
    logger.info(f"🌞 System UNFROZEN (was: {old_reason})")
    
    # Send Telegram alert
    try:
        from utils.telegram_notifier import notify_info
        import asyncio
        asyncio.create_task(notify_info(
            f"🌞 AlgoGPT UNFROZEN\n"
            f"Stage: {_current_stage}\n"
            f"Previous reason: {old_reason}\n"
            f"Action: Auto-promotion resumed"
        ))
    except Exception as e:
        logger.error(f"Failed to send unfreeze notification: {e}")
    
    return True


def promote_stage() -> bool:
    """
    Promote to next stage
    
    Returns:
        True if promoted successfully, False otherwise
    """
    global _current_stage, _stage_start_time
    
    if _frozen:
        logger.warning(f"Cannot promote while frozen: {_freeze_reason}")
        return False
    
    if _current_stage >= 3:
        logger.warning("Already at maximum stage (3)")
        return False
    
    old_stage = _current_stage
    _current_stage += 1
    _stage_start_time = time.time()
    _save_stage()
    _log_stage_history(f"PROMOTED {old_stage} → {_current_stage}")
    
    stage_info = get_stage_info()
    logger.info(
        f"🚀 PROMOTED: Stage {old_stage} → {_current_stage} ({stage_info['name']})\n"
        f"   Description: {stage_info['description']}\n"
        f"   Auto-Run: {stage_info['auto_run']}\n"
        f"   Trading: {stage_info['enable_auto_trading']}"
    )
    
    # Send Telegram alert
    try:
        from utils.telegram_notifier import notify_info
        import asyncio
        asyncio.create_task(notify_info(
            f"🚀 Stage Promotion!\n"
            f"Stage {old_stage} → Stage {_current_stage}\n\n"
            f"**{stage_info['name']}**\n"
            f"{stage_info['description']}\n\n"
            f"Auto-Run: {'✅' if stage_info['auto_run'] else '❌'}\n"
            f"Trading: {'✅' if stage_info['enable_auto_trading'] else '❌'}"
        ))
    except Exception as e:
        logger.error(f"Failed to send promotion notification: {e}")
    
    return True


def demote_stage(reason: str) -> bool:
    """
    Demote to previous stage (emergency fallback)
    
    Args:
        reason: Reason for demotion
        
    Returns:
        True if demoted successfully
    """
    global _current_stage, _stage_start_time
    
    if _current_stage <= 1:
        logger.warning("Already at minimum stage (1), freezing instead")
        return freeze_stage(reason)
    
    old_stage = _current_stage
    _current_stage -= 1
    _stage_start_time = time.time()
    _save_stage()
    _log_stage_history(f"DEMOTED {old_stage} → {_current_stage} (reason: {reason})")
    
    stage_info = get_stage_info()
    logger.warning(
        f"⬇️ DEMOTED: Stage {old_stage} → {_current_stage} ({stage_info['name']})\n"
        f"   Reason: {reason}"
    )
    
    # Send Telegram alert
    try:
        from utils.telegram_notifier import notify_error
        import asyncio
        asyncio.create_task(notify_error(
            f"⬇️ Stage Demotion!\n"
            f"Stage {old_stage} → Stage {_current_stage}\n\n"
            f"Reason: {reason}\n\n"
            f"**{stage_info['name']}**\n"
            f"{stage_info['description']}"
        ))
    except Exception as e:
        logger.error(f"Failed to send demotion notification: {e}")
    
    return True


def get_stage_status() -> Dict[str, Any]:
    """Get comprehensive stage status"""
    stage_info = get_stage_info()
    uptime_hours = get_stage_uptime_hours()
    
    return {
        "stage": _current_stage,
        "stage_name": stage_info["name"],
        "stage_description": stage_info["description"],
        "frozen": _frozen,
        "freeze_reason": _freeze_reason,
        "uptime_hours": uptime_hours,
        "uptime_minutes": uptime_hours * 60,
        "started_at": _stage_start_time,
        "config": {
            "auto_run": stage_info["auto_run"],
            "enable_auto_trading": stage_info["enable_auto_trading"],
            "manage_trades": stage_info["manage_trades"],
            "pool_per_cycle": stage_info["pool_per_cycle"]
        },
        "promotion_criteria": stage_info.get("promotion_criteria"),
        "can_promote": _current_stage < 3 and not _frozen
    }


# Initialize on import
load_current_stage()
