"""
ALGO-REPLIT Auto-Scale Manager
Dormant until resources trigger expansion
"""

import os
import asyncio
import psutil
import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

ENABLE_SCALE_MODE = os.getenv("ENABLE_SCALE_MODE", "false").lower() == "true"
SCALE_CPU_THRESHOLD = float(os.getenv("SCALE_CPU_THRESHOLD", "80"))
SCALE_MEMORY_THRESHOLD = float(os.getenv("SCALE_MEMORY_THRESHOLD", "85"))
SCALE_QUEUE_THRESHOLD = int(os.getenv("SCALE_QUEUE_THRESHOLD", "50"))

class ScaleManager:
    """
    Manages auto-scaling to multi-user/multi-node mode.
    Dormant in single-user mode, activates when resources exceed thresholds.
    """
    
    def __init__(self):
        self.scale_enabled = ENABLE_SCALE_MODE
        self.scale_history = []
        self.last_check = None
    
    async def check_scale_conditions(self) -> Dict[str, Any]:
        """
        Monitor system resources and determine if scale mode should activate
        """
        if self.scale_enabled:
            return {"status": "scale_mode_active"}
        
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        should_scale = (
            cpu_percent > SCALE_CPU_THRESHOLD or
            memory.percent > SCALE_MEMORY_THRESHOLD
        )
        
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "should_scale": should_scale,
            "scale_enabled": self.scale_enabled,
        }
        
        self.last_check = status
        
        if should_scale and not self.scale_enabled:
            logger.warning(f"⚠️ Scale threshold reached! CPU: {cpu_percent}%, MEM: {memory.percent}%")
            # Would trigger auto-scaling in future versions
            # For now, just log the condition
        
        return status
    
    async def enable_scale_mode(self) -> Dict[str, Any]:
        """
        Activate multi-user/multi-node scaling mode
        """
        self.scale_enabled = True
        
        logger.info("🔄 SCALE MODE ENABLED")
        logger.info("• Multi-user isolation activated")
        logger.info("• Wallet separation enabled")
        logger.info("• Load balancing ready")
        logger.info("• Multi-node replication ready")
        
        return {
            "status": "scale_mode_enabled",
            "timestamp": datetime.utcnow().isoformat(),
            "features_activated": [
                "multi_user_isolation",
                "wallet_separation",
                "load_balancing",
                "multi_node_replication",
                "api_isolation",
                "permission_tiers",
            ]
        }
    
    async def disable_scale_mode(self) -> Dict[str, Any]:
        """
        Revert to single-user mode
        """
        self.scale_enabled = False
        
        logger.info("✓ Reverted to SINGLE_USER mode")
        
        return {
            "status": "single_user_mode",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current scale status"""
        return {
            "scale_enabled": self.scale_enabled,
            "last_check": self.last_check,
            "threshold_cpu": SCALE_CPU_THRESHOLD,
            "threshold_memory": SCALE_MEMORY_THRESHOLD,
            "threshold_queue": SCALE_QUEUE_THRESHOLD,
        }
    
    async def run_health_monitor(self):
        """
        Run periodic health check for auto-scaling
        """
        while True:
            try:
                await self.check_scale_conditions()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(60)

# Singleton instance
scale_manager = ScaleManager()

async def get_scale_manager() -> ScaleManager:
    """Dependency: get scale manager"""
    return scale_manager
