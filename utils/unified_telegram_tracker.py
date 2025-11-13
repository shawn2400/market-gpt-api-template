#!/usr/bin/env python3
# utils/unified_telegram_tracker.py
"""
Unified Telegram Message Tracker
Manages single message per symbol that updates from Entry → Opened → Closed
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger("unified_telegram")

TRACKER_FILE = Path("data/telegram_message_tracker.json")

class UnifiedMessageTracker:
    """Track Telegram message IDs for unified updates"""
    
    def __init__(self):
        self.messages: Dict[str, Dict[str, Any]] = {}
        self._load()
    
    def _load(self):
        """Load from file"""
        if TRACKER_FILE.exists():
            try:
                self.messages = json.loads(TRACKER_FILE.read_text())
                logger.info(f"Loaded {len(self.messages)} tracked messages")
            except Exception as e:
                logger.error(f"Failed to load tracker: {e}")
                self.messages = {}
    
    def _save(self):
        """Save to file"""
        try:
            TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
            TRACKER_FILE.write_text(json.dumps(self.messages, indent=2))
        except Exception as e:
            logger.error(f"Failed to save tracker: {e}")
    
    def register_entry(self, symbol: str, message_id: int, chat_id: int, entry_data: Dict[str, Any]):
        """Register new entry message"""
        self.messages[symbol] = {
            "message_id": message_id,
            "chat_id": chat_id,
            "status": "PENDING",
            "entry_time": datetime.now().isoformat(),
            "entry_data": entry_data
        }
        self._save()
        logger.info(f"Registered entry message for {symbol}: msg_id={message_id}")
    
    def update_opened(self, symbol: str, open_data: Dict[str, Any]):
        """Update status to OPENED"""
        if symbol in self.messages:
            self.messages[symbol]["status"] = "OPENED"
            self.messages[symbol]["open_time"] = datetime.now().isoformat()
            self.messages[symbol]["open_data"] = open_data
            self._save()
            logger.info(f"Updated {symbol} to OPENED")
            return self.messages[symbol]
        return None
    
    def update_closed(self, symbol: str, close_data: Dict[str, Any]):
        """Update status to CLOSED"""
        if symbol in self.messages:
            self.messages[symbol]["status"] = "CLOSED"
            self.messages[symbol]["close_time"] = datetime.now().isoformat()
            self.messages[symbol]["close_data"] = close_data
            self._save()
            logger.info(f"Updated {symbol} to CLOSED")
            return self.messages[symbol]
        return None
    
    def get_message(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get tracked message for symbol"""
        return self.messages.get(symbol)
    
    def remove(self, symbol: str):
        """Remove tracked message after final update"""
        if symbol in self.messages:
            del self.messages[symbol]
            self._save()
            logger.info(f"Removed tracking for {symbol}")
    
    def cleanup_old(self, hours: int = 24):
        """Remove old messages (older than N hours)"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=hours)
        
        to_remove = []
        for symbol, data in self.messages.items():
            try:
                entry_time = datetime.fromisoformat(data.get("entry_time", ""))
                if entry_time < cutoff:
                    to_remove.append(symbol)
            except Exception:
                pass
        
        for symbol in to_remove:
            del self.messages[symbol]
        
        if to_remove:
            self._save()
            logger.info(f"Cleaned up {len(to_remove)} old messages")

# Global instance
_tracker = UnifiedMessageTracker()

def get_tracker() -> UnifiedMessageTracker:
    """Get global tracker instance"""
    return _tracker

