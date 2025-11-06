# -*- coding: utf-8 -*-
"""
Circuit Breaker
Automatically pauses dynamic management after consecutive failures.
Prevents cascading errors from overwhelming the system.
"""
import time
import os
import logging

log = logging.getLogger(__name__)

MAX_FAILS = int(os.getenv("CB_MAX_FAILS", "5"))
COOLDOWN_S = int(os.getenv("CB_COOLDOWN_SEC", "900"))  # 15 minutes

_state = {
    "fails": 0,
    "until": 0,
    "last_error_time": 0
}


def track(ok: bool) -> None:
    """
    Track operation success/failure and trigger circuit if needed.
    
    Args:
        ok: True if operation succeeded, False if failed
    """
    global _state
    
    now = time.time()
    
    # If circuit is open (cooldown active), don't update failure count
    if now < _state["until"]:
        return
    
    if ok:
        # Success: reset failure counter
        if _state["fails"] > 0:
            log.info(f"[CircuitBreaker] Success after {_state['fails']} failures, resetting counter")
        _state["fails"] = 0
        _state["last_error_time"] = 0
    else:
        # Failure: increment counter
        _state["fails"] += 1
        _state["last_error_time"] = now
        
        log.warning(f"[CircuitBreaker] Failure #{_state['fails']}/{MAX_FAILS}")
        
        # Open circuit if threshold reached
        if _state["fails"] >= MAX_FAILS:
            _state["until"] = now + COOLDOWN_S
            log.error(
                f"[CircuitBreaker] ⚠️ CIRCUIT OPEN! Too many failures ({_state['fails']}). "
                f"Pausing for {COOLDOWN_S}s until {time.strftime('%H:%M:%S', time.localtime(_state['until']))}"
            )


def allow() -> bool:
    """
    Check if operations are allowed (circuit closed).
    
    Returns:
        True if circuit is closed (allow operations)
        False if circuit is open (block operations)
    """
    now = time.time()
    
    if now >= _state["until"]:
        # Circuit closed
        if _state["until"] > 0:
            # Just closed, log it
            log.info(f"[CircuitBreaker] ✅ Circuit closed, resuming operations")
            _state["until"] = 0
            _state["fails"] = 0
        return True
    else:
        # Circuit still open
        remaining = int(_state["until"] - now)
        log.warning(f"[CircuitBreaker] ⛔ Circuit open, {remaining}s remaining")
        return False


def get_status() -> dict:
    """
    Get current circuit breaker status.
    
    Returns:
        Dict with status info
    """
    return {
        "is_open": time.time() < _state["until"],
        "failure_count": _state["fails"],
        "cooldown_until": _state["until"],
        "last_error_time": _state["last_error_time"]
    }
