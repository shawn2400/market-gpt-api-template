"""
Hybrid Router — Route signals through multiple sources
"""
import asyncio
import logging
from typing import Dict, Any, List

logger = logging.getLogger("HybridRouter")

class HybridRouter:
    def __init__(self, plugin_manager):
        self.pm = plugin_manager
    
    async def get_scans(self) -> List[Dict[str, Any]]:
        """Get market scans from all scanner bots"""
        scanners = self.pm.get_by_type("scanner")
        
        tasks = [s.get_market_scan() for s in scanners if s.enabled]
        
        if not tasks:
            logger.warning("⚠️ No scanners available")
            return []
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        scans = [r for r in results if isinstance(r, dict) and "error" not in r]
        logger.info(f"✅ Got {len(scans)} scans from {len(scanners)} scanners")
        
        return scans
    
    async def get_signals(self) -> List[Dict[str, Any]]:
        """Get signals from all signal bots"""
        signal_bots = (
            self.pm.get_by_type("signals") + 
            self.pm.get_by_type("futures_signals") +
            self.pm.get_by_type("indicators")
        )
        
        signals = []
        
        for bot in signal_bots:
            if not bot.enabled:
                continue
            
            if hasattr(bot, 'get_signals'):
                result = await bot.get_signals()
                signals.extend(result.get("signals", []))
            elif hasattr(bot, 'handle_webhook'):
                # TradingView
                pass
        
        logger.info(f"✅ Got {len(signals)} signals from signal bots")
        return signals
    
    async def execute_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute order with priority:
        1. HyperTrader (fastest)
        2. Binance (native)
        3. 3Commas SmartTrade (smart management)
        """
        # Try HyperTrader first
        hyper = self.pm.get("hyper")
        if hyper and hyper.enabled:
            try:
                result = await hyper.execute(order)
                if "error" not in result:
                    logger.info(f"✅ Order executed via HyperTrader")
                    return result
            except Exception as e:
                logger.warning(f"⚠️ HyperTrader failed: {e}")
        
        # Fall back to 3Commas
        threecommas = self.pm.get("3commas")
        if threecommas and threecommas.enabled:
            try:
                result = await threecommas.manage_position(
                    order.get("symbol"),
                    order.get("sl"),
                    order.get("tp")
                )
                if "error" not in result:
                    logger.info(f"✅ Order managed via 3Commas")
                    return result
            except Exception as e:
                logger.warning(f"⚠️ 3Commas failed: {e}")
        
        logger.error("❌ All execution methods failed")
        return {"error": "No available execution method"}
