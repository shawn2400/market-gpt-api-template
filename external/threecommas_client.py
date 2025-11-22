"""
3Commas Client — Position Manager Integration
"""
import os
from typing import Dict, Any

class ThreeCommasClient:
    ptype = "manager"

    def __init__(self, capabilities: Dict[str, Any]):
        self.cap = capabilities
        self.api_key = os.getenv("THREECOMMAS_KEY", "demo")
        self.enabled = True
        self.last_error = None
        self.score = 0

    async def manage_position(self, symbol: str, sl: float, tp: float) -> Dict[str, Any]:
        """Manage open position via SmartTrade"""
        try:
            if not self.enabled:
                return {"error": "disabled"}
            
            if not self.cap.get("smarttrade", False):
                return {"error": "SMARTTRADE_DISABLED_IN_FREE_PLAN"}

            # Placeholder — would connect to real 3Commas API
            return {
                "source": "3commas",
                "status": "executed",
                "symbol": symbol,
                "sl": sl,
                "tp": tp
            }
        except Exception as e:
            self.last_error = str(e)
            return {"error": str(e)}

    def disable(self):
        """Disable this bot"""
        self.enabled = False
    
    def enable(self):
        """Enable this bot"""
        self.enabled = True
    
    def set_score(self, score: float):
        """Set performance score (0-10)"""
        self.score = max(0, min(10, score))
    
    def get_status(self) -> Dict[str, Any]:
        """Get bot status"""
        return {
            "name": "3commas",
            "type": self.ptype,
            "enabled": self.enabled,
            "score": self.score,
            "capabilities": self.cap,
            "last_error": self.last_error
        }
