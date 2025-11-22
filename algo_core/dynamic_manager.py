"""
Dynamic Manager — Real-time SL/TP adjustments
"""
import asyncio
import logging
from typing import Dict, Any, List

logger = logging.getLogger("DynamicManager")

class DynamicManager:
    def __init__(self, interval: int = 4):
        """
        interval: how many seconds between updates
        """
        self.interval = interval
        self.running = False
    
    async def update_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dynamically adjust SL/TP for a position
        Example: trailing stop, breakeven, tighter TP
        """
        # Example: tighten SL by 0.1%, move TP up by 0.2%
        if "sl" in position:
            position["sl"] *= 0.999  # Tighten SL
        
        if "tp" in position:
            position["tp"] *= 1.001  # Move TP higher
        
        return position
    
    async def run(self, open_positions: List[Dict[str, Any]]):
        """
        Continuous loop: update all positions every X seconds
        """
        self.running = True
        logger.info(f"🔄 Dynamic Manager started (update every {self.interval}s)")
        
        while self.running:
            try:
                for pos in open_positions:
                    await self.update_position(pos)
                    logger.debug(f"Updated position: {pos.get('symbol')}")
                
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                logger.info("🛑 Dynamic Manager stopped")
                self.running = False
                break
            except Exception as e:
                logger.error(f"❌ Error in dynamic manager: {e}")
                await asyncio.sleep(self.interval)
    
    def stop(self):
        """Stop the dynamic manager"""
        self.running = False
