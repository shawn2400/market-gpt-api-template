"""
WunderTrading Client — Signal Relay Integration
"""
import os
from typing import Dict, Any, List

class WunderClient:
    ptype = "signals"

    def __init__(self, capabilities: Dict[str, Any]):
        self.cap = capabilities
        self.api_key = os.getenv("WUNDER_KEY", "demo")
        self.enabled = True
        self.last_error = None
        self.score = 0

    async def get_signals(self) -> Dict[str, Any]:
        """Get signals from WunderTrading"""
        try:
            if not self.enabled:
                return {"signals": []}
            
            return {
                "source": "WunderTrading",
                "webhooks": self.cap.get("webhooks", 1),
                "speed": self.cap.get("speed", "low"),
                "signals": []
            }
        except Exception as e:
            self.last_error = str(e)
            return {"signals": []}

    def disable(self):
        self.enabled = False
    
    def enable(self):
        self.enabled = True
    
    def set_score(self, score: float):
        self.score = max(0, min(10, score))
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "name": "wunder",
            "type": self.ptype,
            "enabled": self.enabled,
            "score": self.score,
            "capabilities": self.cap,
            "last_error": self.last_error
        }
