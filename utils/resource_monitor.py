#!/usr/bin/env python3
"""
Resource Management - Smart CPU/RAM/Memory Monitoring
======================================================
Ensures smooth operation without crashes or freezes.

Features:
- CPU usage monitoring
- RAM usage tracking
- Memory leak detection
- Auto-throttling when resources tight
- Graceful degradation
"""

import logging
import os
import psutil
from typing import Dict, Any, Optional

logger = logging.getLogger("algogpt.resource_monitor")


class ResourceMonitor:
    """
    Monitors system resources and prevents crashes/freezes.
    
    Thresholds:
    - CPU: Warn at 80%, throttle at 90%
    - RAM: Warn at 75%, throttle at 85%
    - Memory: Alert if leak detected
    """
    
    def __init__(self):
        self.logger = logger
        
        self.cpu_warn_threshold = 80.0
        self.cpu_throttle_threshold = 90.0
        
        self.ram_warn_threshold = 75.0
        self.ram_throttle_threshold = 85.0
        
        self.process = psutil.Process()
        self.baseline_memory = self.process.memory_info().rss / 1024 / 1024
        
        self.logger.info(
            f"Resource Monitor initialized | "
            f"Baseline RAM: {self.baseline_memory:.1f} MB"
        )
    
    def get_system_stats(self) -> Dict[str, Any]:
        """
        Get current system resource statistics.
        
        Returns:
            Dict with CPU, RAM, memory stats
        """
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            
            ram = psutil.virtual_memory()
            ram_percent = ram.percent
            ram_available = ram.available / 1024 / 1024 / 1024
            
            process_memory = self.process.memory_info().rss / 1024 / 1024
            memory_growth = process_memory - self.baseline_memory
            
            return {
                "cpu_percent": cpu_percent,
                "ram_percent": ram_percent,
                "ram_available_gb": round(ram_available, 2),
                "process_memory_mb": round(process_memory, 1),
                "memory_growth_mb": round(memory_growth, 1),
                "status": self._get_status(cpu_percent, ram_percent),
                "throttle_needed": cpu_percent > self.cpu_throttle_threshold or ram_percent > self.ram_throttle_threshold
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get system stats: {e}", exc_info=True)
            return {
                "cpu_percent": 0,
                "ram_percent": 0,
                "ram_available_gb": 0,
                "status": "ERROR",
                "error": str(e)
            }
    
    def _get_status(self, cpu: float, ram: float) -> str:
        """Get resource status."""
        if cpu > self.cpu_throttle_threshold or ram > self.ram_throttle_threshold:
            return "CRITICAL"
        elif cpu > self.cpu_warn_threshold or ram > self.ram_warn_threshold:
            return "WARNING"
        else:
            return "OK"
    
    def check_resources(self) -> Dict[str, Any]:
        """
        Check resources and return recommendations.
        
        Returns:
            Dict with status and recommended actions
        """
        try:
            stats = self.get_system_stats()
            
            cpu = stats["cpu_percent"]
            ram = stats["ram_percent"]
            status = stats["status"]
            
            actions = []
            
            if status == "CRITICAL":
                actions.append("THROTTLE_SCANNING")
                actions.append("PAUSE_NON_ESSENTIAL")
                self.logger.warning(
                    f"⚠️ CRITICAL resources: CPU={cpu:.1f}%, RAM={ram:.1f}%"
                )
            
            elif status == "WARNING":
                actions.append("REDUCE_FREQUENCY")
                self.logger.info(
                    f"⚠️ High resource usage: CPU={cpu:.1f}%, RAM={ram:.1f}%"
                )
            
            else:
                actions.append("NORMAL_OPERATION")
                self.logger.debug(f"✅ Resources OK: CPU={cpu:.1f}%, RAM={ram:.1f}%")
            
            if stats.get("memory_growth_mb", 0) > 200:
                actions.append("MEMORY_LEAK_SUSPECTED")
                self.logger.error(
                    f"🔴 Memory leak detected: +{stats['memory_growth_mb']:.1f} MB"
                )
            
            return {
                "status": status,
                "actions": actions,
                "stats": stats,
                "throttle": status == "CRITICAL"
            }
            
        except Exception as e:
            self.logger.error(f"Failed to check resources: {e}", exc_info=True)
            return {
                "status": "ERROR",
                "actions": ["UNKNOWN"],
                "error": str(e)
            }
    
    def should_throttle(self) -> bool:
        """
        Check if system should throttle operations.
        
        Returns:
            True if throttling needed
        """
        try:
            check = self.check_resources()
            return check.get("throttle", False)
            
        except Exception as e:
            self.logger.error(f"Failed to check throttle: {e}", exc_info=True)
            return False
    
    def get_recommended_sleep(self) -> int:
        """
        Get recommended sleep time between operations.
        
        Returns:
            Sleep time in seconds
        """
        try:
            check = self.check_resources()
            status = check.get("status", "OK")
            
            if status == "CRITICAL":
                return 60
            elif status == "WARNING":
                return 30
            else:
                return 10
                
        except Exception as e:
            self.logger.error(f"Failed to get sleep time: {e}", exc_info=True)
            return 10


_resource_monitor: Optional[ResourceMonitor] = None


def get_resource_monitor() -> ResourceMonitor:
    """Get or create Resource Monitor."""
    global _resource_monitor
    if _resource_monitor is None:
        _resource_monitor = ResourceMonitor()
    return _resource_monitor


__all__ = ["ResourceMonitor", "get_resource_monitor"]
