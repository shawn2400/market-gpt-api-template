# utils/multi_tf_manager.py
from __future__ import annotations

"""
MultiTFContextManager - Centralized multi-timeframe context orchestration.
Caches Binance OHLCV data per symbol+interval with TTL to minimize API calls.

**Sniper-Grade Multi-Timeframe Analysis**
- 4H = 50% weight (Primary trend direction)
- 1H = 30% weight (Confirmation)
- 15M = 20% weight (Entry timing only)
"""

import time
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd

from utils.scanner_utils import fetch_ohlcv

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cached OHLCV data with TTL."""
    df: pd.DataFrame
    fetched_at: float
    interval: str
    symbol: str


class MultiTFContextManager:
    """
    Centralized multi-timeframe context manager with smart caching.
    
    Features:
    - Caches OHLCV data per symbol+interval
    - Configurable TTL per timeframe (30s for 15m, 2m for 1h, 5m for 4h)
    - Batch fetch support to minimize API calls
    - Thread-safe with asyncio locks
    - **Timeframe prioritization (4H=50%, 1H=30%, 15M=20%) for sniper-level precision**
    """
    
    # TTL configuration (seconds)
    TTL_CONFIG = {
        "1m": 10,
        "3m": 15,
        "5m": 20,
        "15m": 30,
        "30m": 60,
        "1h": 120,
        "2h": 180,
        "4h": 300,
        "6h": 360,
        "8h": 420,
        "12h": 600,
        "1d": 900,
    }
    
    # Timeframe Priority Weights (for sniper-grade analysis)
    # Higher timeframes = more weight in decision making
    # 4H determines direction, 1H confirms, 15M for entry timing only
    TF_WEIGHTS = {
        "15m": 0.20,  # Entry timing only
        "1h": 0.30,   # Confirmation
        "4h": 0.50,   # Primary trend direction
        "1d": 0.60,   # Long-term bias (if used)
        "1m": 0.05,   # Scalping only
        "5m": 0.10,   # Micro timeframe
        "30m": 0.25,  # Bridge timeframe
        "2h": 0.35,   # Extended confirmation
        "6h": 0.45,   # Strong trend
        "8h": 0.48,   # Very strong trend
        "12h": 0.55,  # Daily trend
    }
    
    # Default timeframe priority (highest to lowest)
    DEFAULT_TF_PRIORITY = ["4h", "1h", "15m"]
    
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._default_ttl = 60
        self.logger = logger
    
    def _cache_key(self, symbol: str, interval: str) -> str:
        """Generate cache key."""
        return f"{symbol.upper()}:{interval}"
    
    def _get_ttl(self, interval: str) -> int:
        """Get TTL for interval."""
        return self.TTL_CONFIG.get(interval, self._default_ttl)
    
    def _is_cached(self, symbol: str, interval: str) -> bool:
        """Check if data is cached and still valid."""
        key = self._cache_key(symbol, interval)
        if key not in self._cache:
            return False
        
        entry = self._cache[key]
        ttl = self._get_ttl(interval)
        age = time.time() - entry.fetched_at
        
        return age < ttl
    
    async def _get_lock(self, symbol: str, interval: str) -> asyncio.Lock:
        """Get or create lock for symbol+interval."""
        key = self._cache_key(symbol, interval)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]
    
    async def fetch_single(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 180,
        force_refresh: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV for single symbol+interval with caching.
        
        Args:
            symbol: Symbol like BTCUSDT
            interval: Timeframe like 15m, 1h, 4h
            limit: Number of candles
            force_refresh: Bypass cache
            
        Returns:
            DataFrame with OHLCV data or None
        """
        symbol = symbol.upper()
        key = self._cache_key(symbol, interval)
        
        # Check cache first (unless force refresh)
        if not force_refresh and self._is_cached(symbol, interval):
            return self._cache[key].df
        
        # Acquire lock to prevent duplicate fetches
        lock = await self._get_lock(symbol, interval)
        async with lock:
            # Double-check cache after acquiring lock
            if not force_refresh and self._is_cached(symbol, interval):
                return self._cache[key].df
            
            # Fetch from API
            df = await fetch_ohlcv(symbol, interval=interval, limit=limit)
            
            if df is not None and len(df) > 0:
                # Cache the result
                self._cache[key] = CacheEntry(
                    df=df,
                    fetched_at=time.time(),
                    interval=interval,
                    symbol=symbol
                )
                return df
            
            return None
    
    async def fetch_batch(
        self,
        symbols: List[str],
        interval: str = "15m",
        limit: int = 180,
        force_refresh: bool = False
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        Fetch OHLCV for multiple symbols in parallel.
        
        Args:
            symbols: List of symbols
            interval: Timeframe
            limit: Number of candles
            force_refresh: Bypass cache
            
        Returns:
            Dict mapping symbol -> DataFrame
        """
        tasks = [
            self.fetch_single(sym, interval, limit, force_refresh)
            for sym in symbols
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        output = {}
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                self.logger.warning(f"Failed to fetch {sym} {interval}: {result}")
                output[sym.upper()] = None
            else:
                output[sym.upper()] = result
        
        return output
    
    async def fetch_batch_multi_tf(
        self,
        symbols: List[str],
        intervals: List[str],
        limit: int = 180,
        force_refresh: bool = False
    ) -> Dict[str, Dict[str, Optional[pd.DataFrame]]]:
        """
        Fetch OHLCV for multiple symbols across multiple timeframes.
        
        This is optimized for the sniper strategy:
        - Prioritizes 4H (50%), 1H (30%), 15M (20%)
        - Fetches all TFs in parallel to minimize latency
        
        Args:
            symbols: List of symbols
            intervals: List of timeframes (e.g., ["4h", "1h", "15m"])
            limit: Number of candles
            force_refresh: Bypass cache
            
        Returns:
            Nested dict: {symbol: {interval: DataFrame}}
        """
        # Create all fetch tasks
        tasks = []
        task_map = []
        
        for symbol in symbols:
            for interval in intervals:
                tasks.append(self.fetch_single(symbol, interval, limit, force_refresh))
                task_map.append((symbol.upper(), interval))
        
        # Execute all fetches in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build nested output dict
        output: Dict[str, Dict[str, Optional[pd.DataFrame]]] = {}
        
        for (symbol, interval), result in zip(task_map, results):
            if symbol not in output:
                output[symbol] = {}
            
            if isinstance(result, Exception):
                self.logger.warning(f"Failed to fetch {symbol} {interval}: {result}")
                output[symbol][interval] = None
            else:
                output[symbol][interval] = result
        
        return output
    
    def get_tf_weight(self, interval: str) -> float:
        """Get priority weight for timeframe."""
        return self.TF_WEIGHTS.get(interval.lower(), 0.15)
    
    def calculate_weighted_signal(
        self,
        signals: Dict[str, float],
        intervals: Optional[List[str]] = None
    ) -> float:
        """
        Calculate weighted average of signals across timeframes.
        
        Args:
            signals: Dict of {interval: signal_value}
            intervals: Optional list to filter/order timeframes
            
        Returns:
            Weighted average signal
        """
        if not signals:
            return 0.0
        
        intervals_to_use = intervals or list(signals.keys())
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for interval in intervals_to_use:
            if interval in signals:
                weight = self.get_tf_weight(interval)
                value = signals[interval]
                
                weighted_sum += weight * value
                total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        return weighted_sum / total_weight
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_entries = len(self._cache)
        valid_entries = sum(
            1 for key in self._cache.keys()
            if self._is_cached(key.split(":")[0], key.split(":")[1])
        )
        
        return {
            "total_entries": total_entries,
            "valid_entries": valid_entries,
            "expired_entries": total_entries - valid_entries,
            "cache_hit_rate": valid_entries / total_entries if total_entries > 0 else 0.0
        }
    
    def clear_cache(self, symbol: Optional[str] = None, interval: Optional[str] = None):
        """Clear cache entries."""
        if symbol and interval:
            key = self._cache_key(symbol, interval)
            self._cache.pop(key, None)
        elif symbol:
            # Clear all intervals for this symbol
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(f"{symbol.upper()}:")]
            for key in keys_to_remove:
                self._cache.pop(key, None)
        else:
            # Clear entire cache
            self._cache.clear()


# Global singleton instance
_manager_instance: Optional[MultiTFContextManager] = None


def get_manager() -> MultiTFContextManager:
    """Get or create global MultiTFContextManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MultiTFContextManager()
        logger.info("✅ MultiTFContextManager initialized with sniper-grade TF weights")
    return _manager_instance
