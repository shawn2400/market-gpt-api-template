"""
Symbol Filter Engine - Pre-trade validation system

Filters symbols based on:
- Market Cap & 24H Volume
- Liquidity depth (order book)
- Binance TOP symbols whitelist
- Performance history
- Blacklist status

Environment Variables:
- FILTER_MIN_24H_VOLUME: Minimum 24H volume in USDT (default: 10,000,000)
- FILTER_MIN_LIQUIDITY_DEPTH: Minimum order book depth in USDT (default: 50,000)
- FILTER_ENABLE_WHITELIST: Enable TOP symbols whitelist (default: 1)
- FILTER_BLOCK_LOW_VOLUME: Block symbols below volume threshold (default: 1)
- SYMBOL_FILTER_ENABLED: Master enable/disable (default: 1)
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger("algogpt.symbol_filter")

# Configuration
SYMBOL_FILTER_ENABLED = os.getenv("SYMBOL_FILTER_ENABLED", "1") == "1"
FILTER_MIN_24H_VOLUME = float(os.getenv("FILTER_MIN_24H_VOLUME", "10000000"))  # $10M
FILTER_MIN_LIQUIDITY_DEPTH = float(os.getenv("FILTER_MIN_LIQUIDITY_DEPTH", "30000"))  # $30k (reduced from $50k to allow more quality symbols)
FILTER_ENABLE_WHITELIST = os.getenv("FILTER_ENABLE_WHITELIST", "0") == "1"  # ✅ DISABLED by default - rely on volume/liquidity instead
FILTER_BLOCK_LOW_VOLUME = os.getenv("FILTER_BLOCK_LOW_VOLUME", "1") == "1"

# TOP Binance Futures symbols (high volume, established)
BINANCE_TOP_SYMBOLS = {
    # Tier A - Blue chips (>$100B market cap)
    "BTCUSDT", "ETHUSDT", "BNBUSDT",
    
    # Tier B - Large caps ($10B-$100B)
    "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "DOGEUSDT",
    "DOTUSDT", "MATICUSDT", "LINKUSDT", "UNIUSDT", "ATOMUSDT",
    
    # Tier C - Mid caps ($1B-$10B)
    "LTCUSDT", "ETCUSDT", "FILUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "NEARUSDT", "INJUSDT", "RUNEUSDT", "LDOUSDT",
    "STXUSDT", "SUIUSDT", "ICPUSDT", "TAOUSDT", "RENDERUSDT",
    
    # Popular altcoins (high volume)
    "FTMUSDT", "GMXUSDT", "AAVEUSDT", "MKRUSDT", "COMPUSDT",
    "SUSHIUSDT", "CAKEUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT",
    "GALAUSDT", "APEUSDT", "CHZUSDT", "ENJUSDT", "FLOWUSDT",
    
    # Layer 2s & Infrastructure
    "STRKUSDT", "ZKUSDT", "METISUSDT", "MANTAUSDT", "BLURUSDT",
    
    # AI & Gaming
    "FETUSDT", "AGIXUSDT", "OCEANUSDT", "GRTUSDT", "RNDRUSDT",
    
    # Meme coins (high volume only)
    "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT"
}


@dataclass
class FilterResult:
    """Filter validation result"""
    passed: bool
    symbol: str
    reason: str = ""
    details: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class SymbolFilterEngine:
    """
    Main symbol filtering engine
    
    Validates symbols before trading based on multiple criteria:
    - Volume & liquidity
    - Whitelist/blacklist
    - Performance history
    """
    
    def __init__(self):
        self.enabled = SYMBOL_FILTER_ENABLED
        self.blacklist: Dict[str, Dict[str, Any]] = {}
        self.symbol_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 300  # 5 minutes
        
        logger.info(
            f"🔍 Symbol Filter Engine initialized | "
            f"Enabled: {self.enabled} | "
            f"Min Volume: ${FILTER_MIN_24H_VOLUME:,.0f} | "
            f"Min Depth: ${FILTER_MIN_LIQUIDITY_DEPTH:,.0f} | "
            f"Whitelist: {FILTER_ENABLE_WHITELIST}"
        )
    
    def validate_symbol(self, symbol: str, **kwargs) -> FilterResult:
        """
        Main validation entry point
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            **kwargs: Additional context (order_type, amount, etc.)
        
        Returns:
            FilterResult with passed/failed status
        """
        if not self.enabled:
            return FilterResult(passed=True, symbol=symbol, reason="Filter disabled")
        
        symbol = symbol.upper()
        
        # 1. Check blacklist first
        blacklist_result = self._check_blacklist(symbol)
        if not blacklist_result.passed:
            return blacklist_result
        
        # 2. Check whitelist (if enabled)
        if FILTER_ENABLE_WHITELIST:
            whitelist_result = self._check_whitelist(symbol)
            if not whitelist_result.passed:
                return whitelist_result
        
        # 3. Check 24H volume
        if FILTER_BLOCK_LOW_VOLUME:
            volume_result = self._check_24h_volume(symbol)
            if not volume_result.passed:
                return volume_result
        
        # 4. Check liquidity depth
        liquidity_result = self._check_liquidity_depth(symbol)
        if not liquidity_result.passed:
            return liquidity_result
        
        # All checks passed
        logger.debug(f"✅ {symbol}: All filters passed")
        return FilterResult(
            passed=True,
            symbol=symbol,
            reason="All validation checks passed",
            details={
                "whitelist": symbol in BINANCE_TOP_SYMBOLS,
                "blacklist": False,
                "volume_ok": True,
                "liquidity_ok": True
            }
        )
    
    def _check_blacklist(self, symbol: str) -> FilterResult:
        """Check if symbol is blacklisted"""
        if symbol not in self.blacklist:
            return FilterResult(passed=True, symbol=symbol)
        
        blacklist_entry = self.blacklist[symbol]
        expiry = blacklist_entry.get("expires_at")
        
        # Check if blacklist expired
        if expiry and datetime.now() > expiry:
            logger.info(f"🔓 {symbol}: Blacklist expired, removing")
            del self.blacklist[symbol]
            return FilterResult(passed=True, symbol=symbol)
        
        # Still blacklisted
        reason = blacklist_entry.get("reason", "Unknown")
        logger.warning(f"🚫 {symbol}: BLOCKED - Blacklisted ({reason})")
        return FilterResult(
            passed=False,
            symbol=symbol,
            reason=f"Symbol blacklisted: {reason}",
            details=blacklist_entry
        )
    
    def _check_whitelist(self, symbol: str) -> FilterResult:
        """Check if symbol is in approved whitelist"""
        if symbol in BINANCE_TOP_SYMBOLS:
            return FilterResult(passed=True, symbol=symbol)
        
        logger.warning(f"⚠️ {symbol}: Not in TOP symbols whitelist")
        return FilterResult(
            passed=False,
            symbol=symbol,
            reason="Symbol not in approved whitelist (TOP 70 symbols only)",
            details={"whitelist_enabled": True, "total_approved": len(BINANCE_TOP_SYMBOLS)}
        )
    
    def _check_24h_volume(self, symbol: str) -> FilterResult:
        """Check 24H trading volume"""
        try:
            # Get from cache first
            cached = self._get_from_cache(symbol, "volume")
            if cached is not None:
                volume_24h = cached
            else:
                # Fetch from Binance
                volume_24h = self._fetch_24h_volume(symbol)
                self._update_cache(symbol, "volume", volume_24h)
            
            if volume_24h >= FILTER_MIN_24H_VOLUME:
                return FilterResult(passed=True, symbol=symbol)
            
            logger.warning(
                f"⚠️ {symbol}: Low 24H volume ${volume_24h:,.0f} "
                f"(min: ${FILTER_MIN_24H_VOLUME:,.0f})"
            )
            return FilterResult(
                passed=False,
                symbol=symbol,
                reason=f"24H volume ${volume_24h:,.0f} below minimum ${FILTER_MIN_24H_VOLUME:,.0f}",
                details={"volume_24h": volume_24h, "min_required": FILTER_MIN_24H_VOLUME}
            )
        
        except Exception as e:
            logger.error(f"❌ {symbol}: Volume check failed: {e}")
            # Fail-open: allow if can't check
            return FilterResult(
                passed=True,
                symbol=symbol,
                reason=f"Volume check failed (allowed): {e}"
            )
    
    def _check_liquidity_depth(self, symbol: str) -> FilterResult:
        """Check order book liquidity depth"""
        try:
            # SKIP liquidity check for TOP 50 symbols - they're pre-validated
            from utils.redis_client import get_redis
            import json
            r = get_redis()
            if r:  # Guard: only bypass if Redis is available
                top50_data = r.get('top50:approved_list')
                if top50_data:
                    top50_symbols = json.loads(top50_data)
                    if symbol in top50_symbols:
                        return FilterResult(
                            passed=True,
                            symbol=symbol,
                            reason="TOP 50 symbol - liquidity pre-validated"
                        )
            
            # Get from cache first
            cached = self._get_from_cache(symbol, "liquidity")
            if cached is not None:
                bid_depth, ask_depth = cached
            else:
                # Fetch order book
                bid_depth, ask_depth = self._fetch_order_book_depth(symbol)
                self._update_cache(symbol, "liquidity", (bid_depth, ask_depth))
            
            min_depth = min(bid_depth, ask_depth)
            
            if min_depth >= FILTER_MIN_LIQUIDITY_DEPTH:
                return FilterResult(passed=True, symbol=symbol)
            
            logger.warning(
                f"⚠️ {symbol}: Low liquidity depth ${min_depth:,.0f} "
                f"(min: ${FILTER_MIN_LIQUIDITY_DEPTH:,.0f})"
            )
            return FilterResult(
                passed=False,
                symbol=symbol,
                reason=f"Liquidity depth ${min_depth:,.0f} below minimum ${FILTER_MIN_LIQUIDITY_DEPTH:,.0f}",
                details={
                    "bid_depth": bid_depth,
                    "ask_depth": ask_depth,
                    "min_depth": min_depth,
                    "min_required": FILTER_MIN_LIQUIDITY_DEPTH
                }
            )
        
        except Exception as e:
            logger.error(f"❌ {symbol}: Liquidity check failed: {e}")
            # Fail-open: allow if can't check
            return FilterResult(
                passed=True,
                symbol=symbol,
                reason=f"Liquidity check failed (allowed): {e}"
            )
    
    def _fetch_24h_volume(self, symbol: str) -> float:
        """Fetch 24H volume from Binance"""
        try:
            from utils.binance_client import client
            ticker = client.futures_ticker(symbol=symbol)
            volume_usdt = float(ticker.get("quoteVolume", 0))
            return volume_usdt
        except Exception as e:
            logger.debug(f"Volume fetch failed for {symbol}: {e}")
            return 0.0
    
    def _fetch_order_book_depth(self, symbol: str) -> Tuple[float, float]:
        """
        Fetch order book depth (top 100 levels for better accuracy)
        
        Returns:
            (bid_depth_usdt, ask_depth_usdt)
        """
        try:
            from utils.binance_client import client
            book = client.futures_order_book(symbol=symbol, limit=100)
            
            # Calculate bid depth (sum of bid quantities * prices)
            bid_depth = sum(
                float(bid[0]) * float(bid[1])
                for bid in book.get("bids", [])
            )
            
            # Calculate ask depth
            ask_depth = sum(
                float(ask[0]) * float(ask[1])
                for ask in book.get("asks", [])
            )
            
            return bid_depth, ask_depth
        
        except Exception as e:
            logger.debug(f"Order book fetch failed for {symbol}: {e}")
            return 0.0, 0.0
    
    def add_to_blacklist(
        self,
        symbol: str,
        reason: str,
        duration_hours: int = 24
    ) -> None:
        """
        Add symbol to blacklist
        
        Args:
            symbol: Symbol to blacklist
            reason: Reason for blacklisting
            duration_hours: How long to blacklist (0 = permanent)
        """
        symbol = symbol.upper()
        expires_at = None
        
        if duration_hours > 0:
            expires_at = datetime.now() + timedelta(hours=duration_hours)
        
        self.blacklist[symbol] = {
            "reason": reason,
            "blacklisted_at": datetime.now(),
            "expires_at": expires_at,
            "duration_hours": duration_hours
        }
        
        logger.warning(
            f"🚫 {symbol}: Added to blacklist | "
            f"Reason: {reason} | "
            f"Duration: {duration_hours}h"
        )
    
    def remove_from_blacklist(self, symbol: str) -> bool:
        """Remove symbol from blacklist"""
        symbol = symbol.upper()
        if symbol in self.blacklist:
            del self.blacklist[symbol]
            logger.info(f"🔓 {symbol}: Removed from blacklist")
            return True
        return False
    
    def get_blacklist(self) -> Dict[str, Dict[str, Any]]:
        """Get current blacklist"""
        # Clean expired entries
        now = datetime.now()
        expired = [
            sym for sym, data in self.blacklist.items()
            if data.get("expires_at") and now > data["expires_at"]
        ]
        for sym in expired:
            del self.blacklist[sym]
        
        return self.blacklist.copy()
    
    def _get_from_cache(self, symbol: str, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        if symbol not in self.symbol_cache:
            return None
        
        cache_entry = self.symbol_cache[symbol]
        if key not in cache_entry:
            return None
        
        data, timestamp = cache_entry[key]
        
        # Check if expired
        if (datetime.now() - timestamp).total_seconds() > self.cache_ttl:
            return None
        
        return data
    
    def _update_cache(self, symbol: str, key: str, value: Any) -> None:
        """Update cache with new value"""
        if symbol not in self.symbol_cache:
            self.symbol_cache[symbol] = {}
        
        self.symbol_cache[symbol][key] = (value, datetime.now())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get filter statistics"""
        return {
            "enabled": self.enabled,
            "whitelist_enabled": FILTER_ENABLE_WHITELIST,
            "approved_symbols": len(BINANCE_TOP_SYMBOLS),
            "blacklisted_symbols": len(self.blacklist),
            "cached_symbols": len(self.symbol_cache),
            "min_volume": FILTER_MIN_24H_VOLUME,
            "min_liquidity_depth": FILTER_MIN_LIQUIDITY_DEPTH
        }


# Singleton instance
_filter_engine: Optional[SymbolFilterEngine] = None


def get_symbol_filter() -> SymbolFilterEngine:
    """Get or create singleton filter engine"""
    global _filter_engine
    if _filter_engine is None:
        _filter_engine = SymbolFilterEngine()
    return _filter_engine


# Convenience function
def validate_symbol(symbol: str, **kwargs) -> FilterResult:
    """Quick symbol validation"""
    engine = get_symbol_filter()
    return engine.validate_symbol(symbol, **kwargs)


# Public API
__all__ = [
    "SymbolFilterEngine",
    "FilterResult",
    "get_symbol_filter",
    "validate_symbol",
    "BINANCE_TOP_SYMBOLS"
]
