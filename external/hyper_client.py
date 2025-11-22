"""
HyperTrader Client — Fast Execution Integration
"""
import os
from typing import Dict, Any

class HyperTraderClient:
    ptype = "execution"

    def __init__(self, capabilities: Dict[str, Any]):
        self.cap = capabilities
        self.api_key = os.getenv("HYPER_KEY", "demo")
        self.enabled = True
        self.last_error = None
        self.score = 0

    async def execute(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Execute order with HyperTrader"""
        try:
            if not self.enabled:
                return {"error": "disabled"}
            
            return {
                "source": "HyperTrader",
                "latency": self.cap.get("latency", "normal"),
                "result": "ok",
                "order": order
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
            "name": "hyper",
            "type": self.ptype,
            "enabled": self.enabled,
            "score": self.score,
            "capabilities": self.cap,
            "last_error": self.last_error
        }
