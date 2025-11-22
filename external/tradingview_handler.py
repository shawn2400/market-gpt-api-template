"""
TradingView Handler — Indicator & Webhook Integration
"""
import os
from typing import Dict, Any

class TVWebhookHandler:
    ptype = "indicators"

    def __init__(self, capabilities: Dict[str, Any]):
        self.cap = capabilities
        self.api_key = os.getenv("TV_KEY", "demo")
        self.enabled = True
        self.last_error = None
        self.score = 0

    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle TradingView webhook alert"""
        try:
            if not self.enabled:
                return {"error": "disabled"}
            
            return {
                "source": "TradingView",
                "pinescript": self.cap.get("pinescript", "limited"),
                "status": "processed",
                "payload": payload
            }
        except Exception as e:
            self.last_error = str(e)
            return {"error": str(e)}

    def disable(self):
        self.enabled = False
    
    def enable(self):
        self.enabled = True
    
    def set_score(self, score: float):
        self.score = max(0, min(10, score))
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "name": "tradingview",
            "type": self.ptype,
            "enabled": self.enabled,
            "score": self.score,
            "capabilities": self.cap,
            "last_error": self.last_error
        }
