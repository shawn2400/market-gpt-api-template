"""Auto-Pilot Integration with AlgoGPT"""

import requests
import os
import asyncio
from typing import Dict, Any

ALGO_API_URL = os.getenv("ALGO_API_URL", "http://localhost:5000")
ALGO_API_TOKEN = os.getenv("ALGO_API_TOKEN", "")

class AutoPilot:
    def __init__(self):
        self.enabled = bool(ALGO_API_TOKEN)
        self.poll_interval = int(os.getenv("AUTOPILOT_POLL_INTERVAL", "20"))
    
    def get_trade_signal(self) -> Dict[str, Any]:
        """Get next trade signal from AlgoGPT"""
        if not self.enabled:
            return {"status": "disabled"}
        
        try:
            response = requests.get(
                f"{ALGO_API_URL}/autopilot/next",
                headers={"Authorization": f"Bearer {ALGO_API_TOKEN}"},
                timeout=8
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def execute_decision(self, exec_func, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Execute trade decision"""
        action = signal.get("action")
        
        if action == "open":
            symbol = signal.get("symbol")
            size = signal.get("size", 1)
            return exec_func(f"binance_open {symbol} {size}")
        
        elif action == "close":
            symbol = signal.get("symbol")
            return exec_func(f"binance_close {symbol}")
        
        return {"status": "ignored", "message": "Unknown action"}
    
    async def autopilot_loop(self, exec_func):
        """Main autopilot loop"""
        if not self.enabled:
            return
        
        while True:
            try:
                signal = self.get_trade_signal()
                
                if signal.get("status") == "ready":
                    result = self.execute_decision(exec_func, signal)
                    print(f"[AUTOPILOT] Executed: {result}")
                
            except Exception as e:
                print(f"[AUTOPILOT] Error: {e}")
            
            await asyncio.sleep(self.poll_interval)

# Singleton
autopilot = AutoPilot()
