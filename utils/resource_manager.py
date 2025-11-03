#!/usr/bin/env python3
# utils/resource_manager.py
"""
Smart Resource Manager - CPU/Memory Monitoring & Throttling
Production-ready resource management with minimal dependencies
"""
import os
import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.resource_manager")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available - resource monitoring limited")

MAX_CPU_PERCENT = float(os.getenv("MAX_CPU_PERCENT", "85.0"))
MAX_MEMORY_PERCENT = float(os.getenv("MAX_MEMORY_PERCENT", "85.0"))
RESOURCE_CHECK_INTERVAL = int(os.getenv("RESOURCE_CHECK_INTERVAL_SEC", "30"))

_last_check_time = 0.0
_last_check_result: Optional[Dict[str, Any]] = None

class ResourceManager:
    """Lightweight resource monitoring and management"""
    
    def __init__(self, max_cpu_pct: float = MAX_CPU_PERCENT, max_mem_pct: float = MAX_MEMORY_PERCENT):
        self.max_cpu_pct = max_cpu_pct
        self.max_mem_pct = max_mem_pct
        self.enabled = PSUTIL_AVAILABLE
        
    def get_current_usage(self) -> Dict[str, Any]:
        """Get current CPU and memory usage"""
        if not self.enabled or not PSUTIL_AVAILABLE:
            return {
                "ok": True,
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "available": False,
                "reason": "psutil_unavailable"
            }
        
        try:
            import psutil as ps
            cpu_pct = ps.cpu_percent(interval=0.1)
            mem = ps.virtual_memory()
            mem_pct = mem.percent
            
            return {
                "ok": True,
                "cpu_percent": cpu_pct,
                "memory_percent": mem_pct,
                "memory_available_mb": mem.available / (1024 * 1024),
                "available": True
            }
        except Exception as e:
            logger.warning(f"Failed to get resource usage: {e}")
            return {
                "ok": False,
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "available": False,
                "error": str(e)
            }
    
    def is_resource_available(self) -> Dict[str, Any]:
        """
        Check if system resources are within acceptable limits
        Returns: {"ok": bool, "reason": str, "cpu_percent": float, "memory_percent": float}
        """
        usage = self.get_current_usage()
        
        if not usage.get("available"):
            return {
                "ok": True,
                "reason": "monitoring_unavailable",
                "cpu_percent": 0.0,
                "memory_percent": 0.0
            }
        
        cpu = usage.get("cpu_percent", 0.0)
        mem = usage.get("memory_percent", 0.0)
        
        if cpu > self.max_cpu_pct:
            return {
                "ok": False,
                "reason": f"cpu_overload_{cpu:.1f}%_exceeds_{self.max_cpu_pct}%",
                "cpu_percent": cpu,
                "memory_percent": mem
            }
        
        if mem > self.max_mem_pct:
            return {
                "ok": False,
                "reason": f"memory_overload_{mem:.1f}%_exceeds_{self.max_mem_pct}%",
                "cpu_percent": cpu,
                "memory_percent": mem
            }
        
        return {
            "ok": True,
            "reason": "resources_available",
            "cpu_percent": cpu,
            "memory_percent": mem
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive resource statistics"""
        usage = self.get_current_usage()
        limits_check = self.is_resource_available()
        
        return {
            "enabled": self.enabled,
            "current": usage,
            "limits": {
                "max_cpu_pct": self.max_cpu_pct,
                "max_mem_pct": self.max_mem_pct
            },
            "status": limits_check
        }

_global_manager: Optional[ResourceManager] = None

def get_resource_manager() -> ResourceManager:
    """Get or create global resource manager singleton"""
    global _global_manager
    if _global_manager is None:
        _global_manager = ResourceManager()
    return _global_manager

def check_resources_cached(cache_ttl_sec: int = RESOURCE_CHECK_INTERVAL) -> Dict[str, Any]:
    """
    Cached resource check to avoid excessive CPU usage from monitoring itself
    Returns the last check if within TTL, otherwise performs new check
    """
    global _last_check_time, _last_check_result
    
    now = time.time()
    if _last_check_result and (now - _last_check_time) < cache_ttl_sec:
        return _last_check_result
    
    mgr = get_resource_manager()
    _last_check_result = mgr.is_resource_available()
    _last_check_time = now
    
    return _last_check_result

def wait_for_resources(timeout_sec: float = 60.0, check_interval: float = 2.0) -> bool:
    """
    Wait until resources are available or timeout
    Returns True if resources available, False on timeout
    """
    mgr = get_resource_manager()
    start = time.time()
    
    while (time.time() - start) < timeout_sec:
        check = mgr.is_resource_available()
        if check["ok"]:
            return True
        
        logger.info(f"Resources limited: {check['reason']} - waiting...")
        time.sleep(check_interval)
    
    logger.warning(f"Resource wait timeout after {timeout_sec}s")
    return False

__all__ = [
    "ResourceManager",
    "get_resource_manager",
    "check_resources_cached",
    "wait_for_resources"
]
