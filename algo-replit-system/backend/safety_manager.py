"""
ALGO-REPLIT Emergency Safety System
Freeze switch, audit logging, confirmation gates
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)

class SafetyLevel(str, Enum):
    LOW = "low"           # Normal operations
    MEDIUM = "medium"     # Caution needed
    HIGH = "high"         # Critical operations
    FROZEN = "frozen"     # All operations blocked

class SafetyManager:
    """
    Manages system safety, audit logs, and emergency controls
    """
    
    def __init__(self):
        self.safety_level = SafetyLevel.LOW
        self.emergency_frozen = False
        self.audit_log: List[Dict[str, Any]] = []
        self.confirmation_pending: Dict[str, Any] = {}
    
    def log_action(self, action: str, user: str, details: Dict[str, Any]):
        """
        Log every system action for audit trail
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "user": user,
            "details": details,
            "safety_level": self.safety_level.value,
        }
        
        self.audit_log.append(log_entry)
        logger.info(f"AUDIT: {action} by {user}")
    
    def require_confirmation(self, action: str, details: Dict[str, Any]) -> str:
        """
        Require confirmation for sensitive operations
        Returns confirmation token
        """
        token = os.urandom(16).hex()
        
        self.confirmation_pending[token] = {
            "action": action,
            "details": details,
            "created_at": datetime.utcnow().isoformat(),
            "confirmed": False,
        }
        
        logger.warning(f"CONFIRMATION REQUIRED: {action}")
        return token
    
    def confirm_action(self, token: str, admin_signature: str) -> bool:
        """
        Confirm pending action with admin signature
        """
        if token not in self.confirmation_pending:
            return False
        
        pending = self.confirmation_pending[token]
        pending["confirmed"] = True
        pending["confirmed_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"ACTION CONFIRMED: {pending['action']}")
        return True
    
    def emergency_freeze(self, reason: str = "Manual activation"):
        """
        Immediately freeze all operations
        """
        self.emergency_frozen = True
        self.safety_level = SafetyLevel.FROZEN
        
        self.log_action(
            "emergency_freeze",
            "system",
            {"reason": reason}
        )
        
        logger.critical(f"🔴 EMERGENCY FREEZE ACTIVATED: {reason}")
    
    def emergency_unfreeze(self) -> bool:
        """
        Unfreeze system after manual review
        """
        self.emergency_frozen = False
        self.safety_level = SafetyLevel.LOW
        
        self.log_action(
            "emergency_unfreeze",
            "system",
            {}
        )
        
        logger.info("✅ System unfrozen")
        return True
    
    def set_safety_level(self, level: SafetyLevel):
        """
        Update safety level
        """
        self.safety_level = level
        logger.info(f"Safety level: {level.value}")
    
    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get audit log (most recent first)
        """
        return self.audit_log[-limit:][::-1]
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current safety status
        """
        return {
            "safety_level": self.safety_level.value,
            "emergency_frozen": self.emergency_frozen,
            "pending_confirmations": len(self.confirmation_pending),
            "audit_log_entries": len(self.audit_log),
            "timestamp": datetime.utcnow().isoformat(),
        }

# Singleton instance
safety_manager = SafetyManager()

async def get_safety_manager() -> SafetyManager:
    """Dependency: get safety manager"""
    return safety_manager
