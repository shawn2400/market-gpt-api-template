"""
🛡️ Binance API Wrapper with Auto-Ban-Shield Integration
Smart wrapper that routes ALL Binance API calls through rate limiting shield

Features:
- Auto-priority classification based on endpoint
- Context-aware throttling
- Seamless integration with existing code
- Zero changes required to existing API calls
"""
import asyncio
import logging
import inspect
from typing import Any, Callable, Optional
from functools import wraps

from utils.ban_shield import get_shield, auto_classify_priority, Priority
from utils.api_call_tracker import get_tracker

logger = logging.getLogger(__name__)

# Enable/disable shield globally
SHIELD_ENABLED = True

def enable_shield():
    """Enable API rate limiting shield"""
    global SHIELD_ENABLED
    SHIELD_ENABLED = True
    logger.info("🛡️ Ban Shield ENABLED")

def disable_shield():
    """Disable API rate limiting shield (for emergencies)"""
    global SHIELD_ENABLED
    SHIELD_ENABLED = False
    logger.warning("⚠️ Ban Shield DISABLED - no rate limiting!")

def shield_binance_api(
    priority: Optional[Priority] = None,
    endpoint_name: Optional[str] = None
):
    """
    Decorator to protect Binance API calls with rate limiting shield
    
    Usage:
        @shield_binance_api(priority="CRITICAL", endpoint_name="new_order")
        def place_order(...):
            ...
    
    Args:
        priority: Override auto-classification (CRITICAL, NORMAL, LOW)
        endpoint_name: Override endpoint detection
    """
    def decorator(func: Callable) -> Callable:
        # Detect if function is async
        is_async = inspect.iscoroutinefunction(func)
        
        if is_async:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                if not SHIELD_ENABLED:
                    # Shield disabled - direct pass-through
                    return await func(*args, **kwargs)
                
                # Get endpoint name
                endpoint = endpoint_name or func.__name__
                
                # Auto-classify priority if not provided
                call_priority = priority or auto_classify_priority(endpoint)
                
                # Get worker name
                worker = "unknown"
                frame = inspect.currentframe()
                if frame and frame.f_back and frame.f_back.f_back:
                    worker = frame.f_back.f_back.f_globals.get('__name__', 'unknown')
                
                # Acquire shield permission
                shield = get_shield()
                tracker = get_tracker()
                
                allowed = await shield.acquire(
                    priority=call_priority,
                    endpoint=endpoint,
                    worker=worker
                )
                
                if not allowed:
                    # Blocked by shield
                    logger.warning(
                        f"🚫 API call blocked: {endpoint} "
                        f"(priority={call_priority}, worker={worker}, "
                        f"zone={shield.current_zone})"
                    )
                    return None
                
                # Record call in tracker
                tracker.record_call(
                    worker=worker,
                    endpoint=endpoint,
                    priority=call_priority,
                    zone=shield.current_zone
                )
                
                # Execute API call
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.error(
                        f"❌ API call failed: {endpoint} - {e}",
                        exc_info=True
                    )
                    raise
            
            return async_wrapper
        
        else:
            # Sync function - convert to async internally
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                if not SHIELD_ENABLED:
                    # Shield disabled - direct pass-through
                    return func(*args, **kwargs)
                
                # Get endpoint name
                endpoint = endpoint_name or func.__name__
                
                # Auto-classify priority if not provided
                call_priority = priority or auto_classify_priority(endpoint)
                
                # Get worker name
                worker = "unknown"
                frame = inspect.currentframe()
                if frame and frame.f_back and frame.f_back.f_back:
                    worker = frame.f_back.f_back.f_globals.get('__name__', 'unknown')
                
                # Acquire shield permission (run async in sync context)
                shield = get_shield()
                tracker = get_tracker()
                
                # Run async acquire in event loop
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                allowed = loop.run_until_complete(
                    shield.acquire(
                        priority=call_priority,
                        endpoint=endpoint,
                        worker=worker
                    )
                )
                
                if not allowed:
                    # Blocked by shield
                    logger.warning(
                        f"🚫 API call blocked: {endpoint} "
                        f"(priority={call_priority}, worker={worker}, "
                        f"zone={shield.current_zone})"
                    )
                    return None
                
                # Record call in tracker
                tracker.record_call(
                    worker=worker,
                    endpoint=endpoint,
                    priority=call_priority,
                    zone=shield.current_zone
                )
                
                # Execute API call
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.error(
                        f"❌ API call failed: {endpoint} - {e}",
                        exc_info=True
                    )
                    raise
            
            return sync_wrapper
    
    return decorator


# Context manager for position-aware operations
class PositionContext:
    """
    Context manager to update shield with current position count
    
    Usage:
        with PositionContext(open_positions=5):
            # API calls here will have boosted priority
            ...
    """
    def __init__(self, open_positions: int):
        self.open_positions = open_positions
        self.shield = get_shield()
    
    def __enter__(self):
        self.shield.set_position_context(self.open_positions)
        return self
    
    def __exit__(self, *args):
        # Reset to 0
        self.shield.set_position_context(0)


# Helper function to update position context globally
def update_position_context(open_positions: int):
    """
    Update shield context with current open positions count
    
    Should be called by position monitor periodically
    """
    shield = get_shield()
    shield.set_position_context(open_positions)
    logger.debug(f"📊 Updated position context: {open_positions} open positions")
