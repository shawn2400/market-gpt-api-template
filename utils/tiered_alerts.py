# utils/tiered_alerts.py
# -*- coding: utf-8 -*-
"""
בס"ד
Tiered Alerting System with 4 levels:
- INFO: New trade opportunity
- WARNING: DD approaching 80% of limit
- CRITICAL: Circuit breaker triggered
- EMERGENCY: System health degraded
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger("algogpt.tiered_alerts")

class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

class TieredAlerting:
    """Tiered alerting system with Telegram integration"""
    
    def __init__(self):
        self.enabled = True
        try:
            from utils.telegram_notifier import notify_telegram
            self.notify_telegram = notify_telegram
            self.telegram_available = True
        except Exception as e:
            logger.warning(f"Telegram notifier not available: {e}")
            self.telegram_available = False
            self.notify_telegram = None
    
    def _get_emoji_and_color(self, level: AlertLevel) -> tuple[str, str]:
        """Get emoji and color formatting for alert level"""
        mapping = {
            AlertLevel.INFO: ("ℹ️", "🔵"),
            AlertLevel.WARNING: ("⚠️", "🟡"),
            AlertLevel.CRITICAL: ("🔴", "🔴"),
            AlertLevel.EMERGENCY: ("🚨", "🔴🚨"),
        }
        return mapping.get(level, ("ℹ️", "🔵"))
    
    async def send_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Send tiered alert via Telegram
        
        Args:
            level: Alert severity level
            title: Alert title
            message: Alert message
            context: Additional context data
            
        Returns:
            bool: True if sent successfully
        """
        if not self.enabled:
            logger.debug(f"Alerts disabled, skipping {level.value} alert: {title}")
            return False
        
        emoji, color = self._get_emoji_and_color(level)
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Build formatted message
        formatted = f"{color} {emoji} **{level.value.upper()}**: {title}\n\n"
        formatted += f"{message}\n\n"
        
        # Add context if provided
        if context:
            formatted += "📊 **Context:**\n"
            for key, value in context.items():
                formatted += f"  • {key}: {value}\n"
        
        formatted += f"\n⏰ {timestamp}"
        
        # Log the alert
        log_method = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.error,
            AlertLevel.EMERGENCY: logger.critical,
        }.get(level, logger.info)
        
        log_method(f"Alert [{level.value}]: {title} - {message}")
        
        # Send via Telegram if available
        if self.telegram_available and self.notify_telegram:
            try:
                await self.notify_telegram(formatted)
                return True
            except Exception as e:
                logger.error(f"Failed to send Telegram alert: {e}")
                return False
        else:
            logger.warning("Telegram not available, alert logged only")
            return False
    
    async def info(self, title: str, message: str, context: Optional[Dict[str, Any]] = None):
        """Send INFO level alert (e.g., new trade opportunity)"""
        await self.send_alert(AlertLevel.INFO, title, message, context)
    
    async def warning(self, title: str, message: str, context: Optional[Dict[str, Any]] = None):
        """Send WARNING level alert (e.g., DD approaching 80% of limit)"""
        await self.send_alert(AlertLevel.WARNING, title, message, context)
    
    async def critical(self, title: str, message: str, context: Optional[Dict[str, Any]] = None):
        """Send CRITICAL level alert (e.g., circuit breaker triggered)"""
        await self.send_alert(AlertLevel.CRITICAL, title, message, context)
    
    async def emergency(self, title: str, message: str, context: Optional[Dict[str, Any]] = None):
        """Send EMERGENCY level alert (e.g., system health degraded)"""
        await self.send_alert(AlertLevel.EMERGENCY, title, message, context)


# Global instance
_alerting_system: Optional[TieredAlerting] = None

def get_alerting_system() -> TieredAlerting:
    """Get or create global alerting system instance"""
    global _alerting_system
    if _alerting_system is None:
        _alerting_system = TieredAlerting()
    return _alerting_system


# Convenience functions
async def send_info_alert(title: str, message: str, context: Optional[Dict[str, Any]] = None):
    """Send INFO level alert"""
    system = get_alerting_system()
    await system.info(title, message, context)


async def send_warning_alert(title: str, message: str, context: Optional[Dict[str, Any]] = None):
    """Send WARNING level alert"""
    system = get_alerting_system()
    await system.warning(title, message, context)


async def send_critical_alert(title: str, message: str, context: Optional[Dict[str, Any]] = None):
    """Send CRITICAL level alert"""
    system = get_alerting_system()
    await system.critical(title, message, context)


async def send_emergency_alert(title: str, message: str, context: Optional[Dict[str, Any]] = None):
    """Send EMERGENCY level alert"""
    system = get_alerting_system()
    await system.emergency(title, message, context)
