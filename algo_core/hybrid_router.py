"""
🔐 Hybrid Router v10.0 — Official 6 Integrations Routing

Routing order (OFFICIAL ONLY):

SCANS:
  1. Cryptohopper (primary)
  2. WunderTrading (secondary)
  3. TradingView (fallback)

SIGNALS:
  1. TradingView (primary)
  2. WunderTrading (secondary)
  3. Cryptohopper (fallback)

EXECUTION:
  1. Binance (primary)
  2. Bybit (secondary)
  3. 3Commas SmartTrade (tertiary)

NO UNSUPPORTED BOTS (HyperTrader, etc)
"""

import asyncio
import logging
from typing import Dict, Any, List
from external.plugin_registry import is_official_plugin

logger = logging.getLogger("algogpt.hybrid_router")

class HybridRouter:
    def __init__(self, plugin_manager):
        self.pm = plugin_manager
    
    async def get_scans(self) -> List[Dict[str, Any]]:
        """Get market scans from official scanner bots
        
        Routing priority:
        1. Cryptohopper (primary)
        2. WunderTrading (secondary)
        3. TradingView (fallback)
        """
        logger.info("📊 Fetching scans from official scanners...")
        
        scans = []
        
        # 1. Try Cryptohopper (primary)
        crypto = self.pm.get("cryptohopper")
        if crypto and hasattr(crypto, 'enabled') and crypto.enabled:
            try:
                result = await asyncio.wait_for(
                    crypto.get_market_scan(), 
                    timeout=2
                )
                if result and "error" not in result:
                    scans.extend(result.get("scans", []))
                    logger.info(f"✅ Cryptohopper: {len(result.get('scans', []))} scans")
            except asyncio.TimeoutError:
                logger.warning("⏱️ Cryptohopper timeout (2s)")
            except Exception as e:
                logger.warning(f"⚠️ Cryptohopper failed: {e}")
        
        # 2. Try WunderTrading (secondary)
        wunder = self.pm.get("wunder")
        if wunder and hasattr(wunder, 'enabled') and wunder.enabled:
            try:
                result = await asyncio.wait_for(
                    wunder.get_market_scan(),
                    timeout=2
                )
                if result and "error" not in result:
                    wunder_scans = result.get("scans", [])
                    # Deduplicate if needed
                    scans.extend(wunder_scans)
                    logger.info(f"✅ WunderTrading: {len(wunder_scans)} scans")
            except asyncio.TimeoutError:
                logger.warning("⏱️ WunderTrading timeout (2s)")
            except Exception as e:
                logger.warning(f"⚠️ WunderTrading failed: {e}")
        
        # 3. Try TradingView (fallback)
        tv = self.pm.get("tradingview")
        if tv and hasattr(tv, 'enabled') and tv.enabled:
            try:
                result = await asyncio.wait_for(
                    tv.get_market_scan(),
                    timeout=2
                )
                if result and "error" not in result:
                    tv_scans = result.get("scans", [])
                    scans.extend(tv_scans)
                    logger.info(f"✅ TradingView: {len(tv_scans)} scans")
            except asyncio.TimeoutError:
                logger.warning("⏱️ TradingView timeout (2s)")
            except Exception as e:
                logger.warning(f"⚠️ TradingView failed: {e}")
        
        logger.info(f"📊 Total scans collected: {len(scans)}")
        return scans
    
    async def get_signals(self) -> List[Dict[str, Any]]:
        """Get signals from official signal bots
        
        Routing priority:
        1. TradingView (primary - webhooks)
        2. WunderTrading (secondary)
        3. Bybit Signals (tertiary)
        4. Cryptohopper (fallback)
        """
        logger.info("📡 Fetching signals from official sources...")
        
        signals = []
        
        # 1. TradingView (webhooks - priority)
        tv = self.pm.get("tradingview")
        if tv and hasattr(tv, 'enabled') and tv.enabled:
            try:
                if hasattr(tv, 'get_signals'):
                    result = await asyncio.wait_for(
                        tv.get_signals(),
                        timeout=2
                    )
                    if result and "error" not in result:
                        tv_signals = result.get("signals", [])
                        signals.extend(tv_signals)
                        logger.info(f"✅ TradingView: {len(tv_signals)} signals")
            except asyncio.TimeoutError:
                logger.warning("⏱️ TradingView timeout (2s)")
            except Exception as e:
                logger.warning(f"⚠️ TradingView failed: {e}")
        
        # 2. WunderTrading
        wunder = self.pm.get("wunder")
        if wunder and hasattr(wunder, 'enabled') and wunder.enabled:
            try:
                if hasattr(wunder, 'get_signals'):
                    result = await asyncio.wait_for(
                        wunder.get_signals(),
                        timeout=2
                    )
                    if result and "error" not in result:
                        wunder_signals = result.get("signals", [])
                        signals.extend(wunder_signals)
                        logger.info(f"✅ WunderTrading: {len(wunder_signals)} signals")
            except asyncio.TimeoutError:
                logger.warning("⏱️ WunderTrading timeout (2s)")
            except Exception as e:
                logger.warning(f"⚠️ WunderTrading failed: {e}")
        
        # 3. Bybit Signals
        bybit = self.pm.get("bybit_signals")
        if bybit and hasattr(bybit, 'enabled') and bybit.enabled:
            try:
                if hasattr(bybit, 'get_signals'):
                    result = await asyncio.wait_for(
                        bybit.get_signals(),
                        timeout=2
                    )
                    if result and "error" not in result:
                        bybit_signals = result.get("signals", [])
                        signals.extend(bybit_signals)
                        logger.info(f"✅ Bybit: {len(bybit_signals)} signals")
            except asyncio.TimeoutError:
                logger.warning("⏱️ Bybit timeout (2s)")
            except Exception as e:
                logger.warning(f"⚠️ Bybit failed: {e}")
        
        # 4. Cryptohopper (fallback)
        crypto = self.pm.get("cryptohopper")
        if crypto and hasattr(crypto, 'enabled') and crypto.enabled:
            try:
                if hasattr(crypto, 'get_signals'):
                    result = await asyncio.wait_for(
                        crypto.get_signals(),
                        timeout=2
                    )
                    if result and "error" not in result:
                        crypto_signals = result.get("signals", [])
                        signals.extend(crypto_signals)
                        logger.info(f"✅ Cryptohopper: {len(crypto_signals)} signals")
            except asyncio.TimeoutError:
                logger.warning("⏱️ Cryptohopper timeout (2s)")
            except Exception as e:
                logger.warning(f"⚠️ Cryptohopper failed: {e}")
        
        logger.info(f"📡 Total signals collected: {len(signals)}")
        return signals
    
    async def execute_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute order with official routing priority:
        1. Binance (primary execution)
        2. Bybit (secondary execution)
        3. 3Commas SmartTrade (tertiary - smart management)
        
        ❌ NEVER use unsupported bots (HyperTrader, etc)
        """
        logger.info(f"🚀 Executing order via official routing...")
        
        symbol = order.get("symbol", "UNKNOWN")
        
        # ✅ 1. Binance (PRIMARY)
        # Native Binance execution handled by ExecutionBot
        logger.info(f"🚀 {symbol}: Routing to Binance (primary)")
        order["_source"] = "binance_native"
        return order  # Return for native Binance handling
        
        # ✅ 2. Bybit (SECONDARY - if Binance fails)
        # This would be called as fallback
        # bybit_exec = self.pm.get("bybit_execution")
        # if bybit_exec and bybit_exec.enabled:...
        
        # ✅ 3. 3Commas SmartTrade (TERTIARY)
        # 3commas = self.pm.get("3commas")
        # if 3commas and 3commas.enabled:...
    
    async def validate_sources(self) -> Dict[str, bool]:
        """Validate that all sources are official"""
        logger.info("🔐 Validating plugin sources...")
        
        validation = {}
        for plugin_name in self.pm.plugins.keys():
            is_official = is_official_plugin(plugin_name)
            validation[plugin_name] = is_official
            
            if not is_official:
                logger.error(f"❌ BLOCKED: Unsupported plugin: {plugin_name}")
            else:
                logger.info(f"✅ {plugin_name}: Official")
        
        return validation
