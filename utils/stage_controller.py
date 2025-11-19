# utils/stage_controller.py
"""
🎯 Stage Controller - Health Monitoring & Auto-Promotion Logic
Evaluates system health and decides when to promote/demote/freeze stages
"""
import os
import logging
import psutil
import time
from typing import Dict, Any, List, Tuple
from utils import stage_engine
from utils.redis_client import get_redis

logger = logging.getLogger("algogpt.stage_controller")

# Configuration
AUTO_PROMOTE_ENABLE = os.getenv("STAGE_AUTO_PROMOTE", "1").lower() in ("1", "true", "yes")
AUTO_FREEZE_ENABLE = os.getenv("STAGE_AUTO_FREEZE", "1").lower() in ("1", "true", "yes")

# Health thresholds (counts over last 10 checks)
ERROR_THRESHOLD = 5
WARNING_THRESHOLD = 10
CPU_THRESHOLD = 90  # %
RAM_THRESHOLD = 85  # %
CONSECUTIVE_FAILURES_TO_FREEZE = 3

# Global state for tracking
_health_history: List[Dict[str, Any]] = []
_consecutive_failures = 0
_last_promotion_time = 0
PROMOTION_COOLDOWN = 600  # 10 minutes between promotions


def evaluate_stage_health() -> Dict[str, Any]:
    """
    Evaluate current system health across all dimensions
    
    Returns:
        Dict with health status, metrics, and issues
    """
    health = {
        "timestamp": time.time(),
        "overall": "GREEN",
        "issues": [],
        "metrics": {},
        "can_promote": False,
        "should_freeze": False,
        "should_demote": False
    }
    
    # 1. CPU Check
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        health["metrics"]["cpu"] = cpu_percent
        
        if cpu_percent > CPU_THRESHOLD:
            health["issues"].append(f"CPU high: {cpu_percent:.1f}%")
            health["overall"] = "YELLOW" if cpu_percent < 95 else "RED"
    except Exception as e:
        logger.error(f"Failed to get CPU: {e}")
        health["metrics"]["cpu"] = 0
    
    # 2. RAM Check
    try:
        ram = psutil.virtual_memory()
        ram_percent = ram.percent
        health["metrics"]["ram"] = ram_percent
        
        if ram_percent > RAM_THRESHOLD:
            health["issues"].append(f"RAM high: {ram_percent:.1f}%")
            if health["overall"] == "GREEN":
                health["overall"] = "YELLOW" if ram_percent < 90 else "RED"
    except Exception as e:
        logger.error(f"Failed to get RAM: {e}")
        health["metrics"]["ram"] = 0
    
    # 3. Redis Check
    try:
        r = get_redis()
        r.ping()
        health["metrics"]["redis"] = "ok"
    except Exception as e:
        health["issues"].append(f"Redis error: {e}")
        health["metrics"]["redis"] = "error"
        health["overall"] = "RED"
    
    # 4. BanShield Zone Check
    try:
        r = get_redis()
        ban_zone = r.get("ban_shield:zone")
        if ban_zone:
            ban_zone = ban_zone.decode() if isinstance(ban_zone, bytes) else ban_zone
        else:
            ban_zone = "unknown"
        
        health["metrics"]["ban_shield_zone"] = ban_zone
        
        if ban_zone == "RED":
            health["issues"].append("BanShield in RED zone")
            if health["overall"] == "GREEN":
                health["overall"] = "YELLOW"
    except Exception as e:
        logger.error(f"Failed to get BanShield zone: {e}")
        health["metrics"]["ban_shield_zone"] = "unknown"
    
    # 5. WebSocket Check (if enabled)
    try:
        from utils import ws_user_stream
        ws_status = ws_user_stream.status()
        ws_running = ws_status.get("running", False)
        health["metrics"]["ws"] = "connected" if ws_running else "disconnected"
        
        if not ws_running and os.getenv("USER_STREAM_ENABLE", "0") == "1":
            health["issues"].append("WebSocket disconnected")
            if health["overall"] == "GREEN":
                health["overall"] = "YELLOW"
    except Exception as e:
        logger.debug(f"WS check skipped: {e}")
        health["metrics"]["ws"] = "n/a"
    
    # 6. Error Count Check (last 10 minutes)
    try:
        r = get_redis()
        error_count = r.get("health:error_count:10m")
        if error_count:
            error_count = int(error_count)
        else:
            error_count = 0
        
        health["metrics"]["errors_10m"] = error_count
        
        if error_count > ERROR_THRESHOLD:
            health["issues"].append(f"High error count: {error_count} errors in 10m")
            health["overall"] = "RED"
        elif error_count > WARNING_THRESHOLD:
            health["issues"].append(f"Warning: {error_count} errors in 10m")
            if health["overall"] == "GREEN":
                health["overall"] = "YELLOW"
    except Exception as e:
        logger.error(f"Failed to get error count: {e}")
        health["metrics"]["errors_10m"] = 0
    
    # 7. Uptime Check
    stage_uptime_hours = stage_engine.get_stage_uptime_hours()
    health["metrics"]["stage_uptime_hours"] = stage_uptime_hours
    
    # Add to history (keep last 20 checks)
    _health_history.append(health)
    if len(_health_history) > 20:
        _health_history.pop(0)
    
    # Decision logic
    current_stage = stage_engine.get_current_stage()
    stage_info = stage_engine.get_stage_info(current_stage)
    promotion_criteria = stage_info.get("promotion_criteria")
    
    # Can promote if criteria met
    if promotion_criteria and not stage_engine.is_frozen():
        can_promote = _check_promotion_criteria(health, promotion_criteria)
        health["can_promote"] = can_promote
    
    # Should freeze if too many issues
    if AUTO_FREEZE_ENABLE and health["overall"] == "RED":
        global _consecutive_failures
        _consecutive_failures += 1
        
        if _consecutive_failures >= CONSECUTIVE_FAILURES_TO_FREEZE:
            health["should_freeze"] = True
            health["freeze_reason"] = f"Health RED for {_consecutive_failures} consecutive checks: {', '.join(health['issues'])}"
    else:
        _consecutive_failures = 0
    
    # Should demote if Stage 3 and health is YELLOW for extended period
    if current_stage == 3 and health["overall"] in ["YELLOW", "RED"]:
        # Check last 5 health checks
        recent_health = _health_history[-5:] if len(_health_history) >= 5 else _health_history
        if len(recent_health) >= 5:
            all_yellow_or_red = all(h["overall"] in ["YELLOW", "RED"] for h in recent_health)
            if all_yellow_or_red:
                health["should_demote"] = True
                health["demote_reason"] = "Health degraded for 5 consecutive checks"
    
    return health


def _check_promotion_criteria(health: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
    """
    Check if promotion criteria are met
    
    Args:
        health: Current health status
        criteria: Promotion criteria from stage config
        
    Returns:
        True if all criteria met
    """
    global _last_promotion_time
    
    # Cooldown check (prevent rapid promotions)
    if time.time() - _last_promotion_time < PROMOTION_COOLDOWN:
        logger.debug(f"Promotion on cooldown ({PROMOTION_COOLDOWN}s)")
        return False
    
    # Overall health must be GREEN
    if health["overall"] != "GREEN":
        logger.debug(f"Health not GREEN: {health['overall']}")
        return False
    
    # Check uptime requirement
    stage_uptime = health["metrics"]["stage_uptime_hours"]
    required_uptime = criteria.get("uptime_hours", 0)
    if stage_uptime < required_uptime:
        logger.debug(f"Uptime {stage_uptime:.1f}h < required {required_uptime}h")
        return False
    
    # Check CPU
    cpu = health["metrics"].get("cpu", 100)
    if cpu > criteria.get("max_cpu", 100):
        logger.debug(f"CPU {cpu:.1f}% > max {criteria['max_cpu']}%")
        return False
    
    # Check RAM
    ram = health["metrics"].get("ram", 100)
    if ram > criteria.get("max_ram", 100):
        logger.debug(f"RAM {ram:.1f}% > max {criteria['max_ram']}%")
        return False
    
    # Check errors
    errors = health["metrics"].get("errors_10m", 999)
    if errors > criteria.get("max_errors", 0):
        logger.debug(f"Errors {errors} > max {criteria['max_errors']}")
        return False
    
    # Check Redis
    if criteria.get("redis_health") == "ok":
        if health["metrics"].get("redis") != "ok":
            logger.debug("Redis not healthy")
            return False
    
    # Check WebSocket (if required)
    if criteria.get("ws_health") == "connected":
        if health["metrics"].get("ws") != "connected":
            logger.debug("WebSocket not connected")
            return False
    
    # Check BanShield zone (if required)
    if criteria.get("ban_shield_zone"):
        required_zone = criteria["ban_shield_zone"].lower()
        current_zone = health["metrics"].get("ban_shield_zone", "unknown").lower()
        if current_zone != required_zone:
            logger.debug(f"BanShield zone {current_zone} != required {required_zone}")
            return False
    
    logger.info("✅ All promotion criteria met!")
    return True


def stage_tick() -> Dict[str, Any]:
    """
    Main tick function - evaluate health and take action
    Called every 60 seconds by stage_watcher
    
    Returns:
        Dict with tick results
    """
    global _last_promotion_time
    
    # Evaluate health
    health = evaluate_stage_health()
    
    result = {
        "timestamp": time.time(),
        "health": health,
        "action_taken": None
    }
    
    # Take action based on health
    if health["should_freeze"]:
        # Freeze system
        success = stage_engine.freeze_stage(health["freeze_reason"])
        if success:
            result["action_taken"] = "freeze"
            logger.warning(f"🥶 FREEZE triggered: {health['freeze_reason']}")
    
    elif health["should_demote"]:
        # Demote stage
        success = stage_engine.demote_stage(health["demote_reason"])
        if success:
            result["action_taken"] = "demote"
            logger.warning(f"⬇️ DEMOTE triggered: {health['demote_reason']}")
    
    elif health["can_promote"] and AUTO_PROMOTE_ENABLE:
        # Promote stage
        success = stage_engine.promote_stage()
        if success:
            result["action_taken"] = "promote"
            _last_promotion_time = time.time()
            logger.info("🚀 PROMOTE triggered")
    
    return result


def send_stage_report_telegram() -> None:
    """Send stage status report to Telegram"""
    try:
        from utils.telegram_notifier import notify_info
        import asyncio
        
        status = stage_engine.get_stage_status()
        health = evaluate_stage_health()
        
        # Build report
        report = (
            f"📊 **AlgoGPT Stage Report**\n\n"
            f"**Stage {status['stage']}: {status['stage_name']}**\n"
            f"{status['stage_description']}\n\n"
            f"⏱️ Uptime: {status['uptime_hours']:.1f}h\n"
            f"{'🥶 FROZEN' if status['frozen'] else '✅ Active'}\n\n"
            f"**Health: {health['overall']}**\n"
            f"CPU: {health['metrics'].get('cpu', 0):.1f}%\n"
            f"RAM: {health['metrics'].get('ram', 0):.1f}%\n"
            f"Redis: {health['metrics'].get('redis', 'unknown')}\n"
            f"BanShield: {health['metrics'].get('ban_shield_zone', 'unknown')}\n"
            f"Errors (10m): {health['metrics'].get('errors_10m', 0)}\n"
        )
        
        if health["issues"]:
            report += f"\n⚠️ Issues:\n"
            for issue in health["issues"]:
                report += f"  • {issue}\n"
        
        asyncio.create_task(notify_info(report))
    except Exception as e:
        logger.error(f"Failed to send stage report: {e}")


def get_stage_summary() -> Dict[str, Any]:
    """Get concise stage summary for API/Telegram"""
    status = stage_engine.get_stage_status()
    health = evaluate_stage_health()
    
    return {
        "stage": status["stage"],
        "stage_name": status["stage_name"],
        "frozen": status["frozen"],
        "uptime_hours": status["uptime_hours"],
        "health": health["overall"],
        "metrics": health["metrics"],
        "issues": health["issues"],
        "can_promote": health.get("can_promote", False)
    }
