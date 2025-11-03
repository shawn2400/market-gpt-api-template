# utils/monitors/circuit_breaker.py
"""
Circuit Breaker System
======================
Auto-protection with daily DD limits, consecutive loss counters, and volatility gates.
"""

from __future__ import annotations
import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import json

logger = logging.getLogger("monitors.circuit_breaker")

try:
    from utils.db import save_breaker_state as db_save_breaker_state, get_latest_breaker_state
    DB_AVAILABLE = True
except ImportError:
    logger.warning("Database functions not available for circuit breaker")
    DB_AVAILABLE = False

@dataclass
class BreakerAction:
    """Circuit breaker action result"""
    triggered: bool
    action: str  # "none", "reduce_50", "pause", "emergency_stop", "pause_manual"
    reason: str
    metrics: Dict[str, Any]
    details: Optional[Dict[str, Any]] = None

# In-memory state (in production, use database)
_breaker_state: Dict[str, Any] = {
    "daily_dd": 0.0,
    "daily_dd_peak": 0.0,
    "consec_losses": 0,
    "last_reset": datetime.now().date().isoformat(),
    "paused": False,
    "pause_reason": "",
}

def check_circuit_breaker(
    current_dd: float,
    consec_losses: int,
    volatility_spike: bool = False,
) -> BreakerAction:
    """
    Check if circuit breakers should trigger.
    
    Args:
        current_dd: Current daily drawdown %
        consec_losses: Number of consecutive losses
        volatility_spike: VIX or volatility spike detected
        
    Returns:
        BreakerAction with decision
    """
    # Load thresholds
    dd_limit = float(os.getenv("BREAKER_DD_LIMIT_PCT", "5.0"))
    consec_limit = int(os.getenv("BREAKER_CONSEC_SL_MAX", "4"))
    action_mode = os.getenv("BREAKER_ACTION", "PAUSE_AND_ALERT")
    
    # Reset daily state if new day
    _reset_daily_if_needed()
    
    # Update state
    _breaker_state["daily_dd"] = current_dd
    _breaker_state["consec_losses"] = consec_losses
    
    if current_dd > _breaker_state["daily_dd_peak"]:
        _breaker_state["daily_dd_peak"] = current_dd
    
    # Check triggers
    triggers = []
    
    if current_dd >= dd_limit:
        triggers.append(f"daily_dd={current_dd:.1f}%>={dd_limit}%")
    
    if consec_losses >= consec_limit:
        triggers.append(f"consec_losses={consec_losses}>={consec_limit}")
    
    if volatility_spike:
        triggers.append("volatility_spike_detected")
    
    # Determine action
    if not triggers:
        return BreakerAction(
            triggered=False,
            action="none",
            reason="All metrics within limits",
            metrics={"dd": current_dd, "consec": consec_losses},
        )
    
    # Breaker triggered
    if len(triggers) >= 2 or current_dd >= dd_limit * 1.5:
        action = "emergency_stop"
    elif consec_losses >= consec_limit + 2:
        action = "pause"
    elif current_dd >= dd_limit:
        action = "pause"
    else:
        action = "reduce_50"
    
    reason = f"BREAKER TRIGGERED: {', '.join(triggers)}"
    
    # Update pause state
    if action in ("pause", "emergency_stop"):
        _breaker_state["paused"] = True
        _breaker_state["pause_reason"] = reason
    
    logger.critical(f"🚨 CIRCUIT BREAKER: {action.upper()} - {reason}")
    
    # Persist state (in production, save to DB)
    _save_breaker_state()
    
    return BreakerAction(
        triggered=True,
        action=action,
        reason=reason,
        metrics={"dd": current_dd, "consec": consec_losses, "triggers": len(triggers)},
    )

def manual_pause(reason: str = "manual_pause") -> BreakerAction:
    """
    Manually pause trading via circuit breaker.
    
    Args:
        reason: Why trading is being paused manually
    
    Returns:
        BreakerAction with triggered=True
    """
    _breaker_state["paused"] = True
    _breaker_state["pause_reason"] = f"MANUAL: {reason}"
    _save_breaker_state()
    
    logger.warning(f"Circuit breaker MANUAL PAUSE: {reason}")
    
    return BreakerAction(
        triggered=True,
        action="pause_manual",
        reason=reason,
        metrics={"manual": True, "timestamp": datetime.now().isoformat()},
    )

def reset_breaker(reason: str = "manual_reset") -> Dict[str, Any]:
    """
    Manually reset circuit breaker.
    
    Returns:
        Dict with reset confirmation
    """
    logger.warning(f"Circuit breaker manually reset: {reason}")
    
    _breaker_state["paused"] = False
    _breaker_state["pause_reason"] = ""
    _breaker_state["consec_losses"] = 0
    
    _save_breaker_state()
    
    return {
        "status": "reset",
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }

def get_breaker_status() -> Dict[str, Any]:
    """Get current breaker status"""
    return dict(_breaker_state)

def _reset_daily_if_needed():
    """Reset daily metrics if new day"""
    today = datetime.now().date().isoformat()
    if _breaker_state["last_reset"] != today:
        logger.info(f"Resetting daily DD metrics for new day: {today}")
        _breaker_state["daily_dd"] = 0.0
        _breaker_state["daily_dd_peak"] = 0.0
        _breaker_state["last_reset"] = today
        _save_breaker_state()

def _save_breaker_state():
    """Persist breaker state to database (with JSON fallback)"""
    if DB_AVAILABLE:
        try:
            db_save_breaker_state(_breaker_state)
            logger.debug("Circuit breaker state saved to database")
            return
        except Exception as e:
            logger.error(f"Failed to save breaker state to database: {e}, falling back to JSON")
    
    try:
        state_file = os.getenv("BREAKER_STATE_FILE", "data/breaker_state.json")
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w") as f:
            json.dump(_breaker_state, f, indent=2)
        logger.debug("Circuit breaker state saved to JSON file")
    except Exception as e:
        logger.error(f"Failed to save breaker state: {e}")

def _load_breaker_state():
    """Load persisted breaker state from database (with JSON fallback)"""
    if DB_AVAILABLE:
        try:
            loaded = get_latest_breaker_state()
            if loaded:
                _breaker_state.update({
                    "daily_dd": loaded.get("daily_dd", 0.0),
                    "daily_dd_peak": loaded.get("daily_dd_peak", 0.0),
                    "consec_losses": loaded.get("consec_losses", 0),
                    "last_reset": loaded.get("last_reset", datetime.now().date().isoformat()),
                    "paused": loaded.get("paused", False),
                    "pause_reason": loaded.get("pause_reason", ""),
                })
                logger.info("Circuit breaker state loaded from database")
                return
        except Exception as e:
            logger.warning(f"Could not load breaker state from database: {e}, falling back to JSON")
    
    try:
        state_file = os.getenv("BREAKER_STATE_FILE", "data/breaker_state.json")
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                loaded = json.load(f)
                _breaker_state.update(loaded)
                logger.info("Circuit breaker state loaded from JSON file")
    except Exception as e:
        logger.warning(f"Could not load breaker state: {e}")

# Load state on module import
_load_breaker_state()
