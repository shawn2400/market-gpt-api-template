# utils/blacklist_forgiveness_manager.py
"""
Blacklist Forgiveness Manager - Auto-Forgiveness for TOP 50 Symbols
====================================================================
Automatically forgives symbols that enter TOP 50 by:
- Removing from temp blacklist
- Reducing failure counters by 50% (preserves history)
- Enforcing 1h cool-off for repeat offenders (≥6 failures)

Runs every 5 minutes, coordinates with ZeroToleranceGatekeeper.

Author: AlgoGPT Team
"""

import json
import logging
import time
from typing import Dict, List, Set, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("algogpt.forgiveness")


class BlacklistForgivenessManager:
    """
    Smart forgiveness system that automatically removes bans for TOP 50 symbols.
    
    Features:
    - Cross-checks blacklist against fresh TOP 50 (< 10min old)
    - Reduces failure counters by 50% instead of full reset (preserves signal)
    - 1h cool-off for symbols with ≥6 failures in 24h
    - Atomic Redis operations to prevent race conditions
    - Fail-open when TOP 50 data is stale
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        
        # Redis keys
        self.temp_blacklist_key = "blacklist:temp"
        self.top_50_key = "top50:approved_list"
        self.failure_count_prefix = "failures:count:"
        self.cooldown_key_prefix = "blacklist:cooldown:"
        self.last_run_key = "forgiveness:last_run"
        
        # Configuration
        self.max_failures_before_cooloff = 6
        self.cooloff_duration_sec = 3600  # 1h
        self.max_top50_age_sec = 600      # 10min
        self.failure_reduction_pct = 50    # Reduce by 50%
        
        logger.info(
            f"BlacklistForgivenessManager initialized | "
            f"Cooloff threshold: {self.max_failures_before_cooloff} failures, "
            f"Duration: {self.cooloff_duration_sec}s, "
            f"Counter reduction: {self.failure_reduction_pct}%"
        )
    
    def run_forgiveness_cycle(self) -> Dict:
        """
        Run one forgiveness cycle - check TOP 50 and forgive eligible symbols.
        
        Returns:
            Dict with forgiveness statistics
        """
        try:
            logger.info("🔄 Starting forgiveness cycle...")
            
            # 1. Get valid TOP 50 (fail-open if stale)
            top_50_symbols = self._get_valid_top_50()
            if not top_50_symbols:
                logger.warning("⚠️ No valid TOP 50 - skipping forgiveness (fail-open)")
                return {'status': 'skipped', 'reason': 'no_valid_top50'}
            
            # 2. Get current blacklist
            blacklisted_symbols = self._get_temp_blacklist()
            if not blacklisted_symbols:
                logger.info("✅ No symbols in blacklist")
                return {'status': 'success', 'forgiven': 0, 'cooloff': 0}
            
            # 3. Find TOP 50 symbols that are blacklisted
            top50_blacklisted = top_50_symbols & blacklisted_symbols
            
            if not top50_blacklisted:
                logger.info(f"✅ No TOP 50 symbols in blacklist ({len(blacklisted_symbols)} total blacklisted)")
                return {'status': 'success', 'forgiven': 0, 'cooloff': 0}
            
            logger.info(f"🎯 Found {len(top50_blacklisted)} TOP 50 symbols in blacklist: {sorted(list(top50_blacklisted))[:5]}...")
            
            # 4. Process each symbol
            results = {
                'forgiven': [],
                'cooloff': [],
                'errors': []
            }
            
            for symbol in top50_blacklisted:
                try:
                    result = self._process_symbol_forgiveness(symbol)
                    if result['action'] == 'FORGIVEN':
                        results['forgiven'].append(result)
                    elif result['action'] == 'COOLOFF':
                        results['cooloff'].append(result)
                except Exception as e:
                    logger.error(f"❌ Failed to process {symbol}: {e}")
                    results['errors'].append({'symbol': symbol, 'error': str(e)})
            
            # 5. Update last run timestamp
            self.redis.set(self.last_run_key, time.time())
            
            logger.info(
                f"✅ Forgiveness cycle complete: "
                f"{len(results['forgiven'])} forgiven, "
                f"{len(results['cooloff'])} on cooloff, "
                f"{len(results['errors'])} errors"
            )
            
            return {
                'status': 'success',
                'forgiven': len(results['forgiven']),
                'cooloff': len(results['cooloff']),
                'errors': len(results['errors']),
                'details': results
            }
            
        except Exception as e:
            logger.error(f"❌ Forgiveness cycle failed: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}
    
    def _get_valid_top_50(self) -> Set[str]:
        """
        Get TOP 50 symbols if data is fresh (< 10min old).
        
        Returns:
            Set of symbol names, or empty set if data is stale/missing
        """
        try:
            # Get TOP 50 data with timestamp
            top50_key_with_ts = "top50:last_update"
            data = self.redis.get(self.top_50_key)
            timestamp_data = self.redis.get(top50_key_with_ts)
            
            if not data:
                logger.warning("⚠️ TOP 50 data not found in Redis")
                return set()
            
            # Check freshness
            if timestamp_data:
                try:
                    last_update = float(timestamp_data)
                    age_sec = time.time() - last_update
                    
                    if age_sec > self.max_top50_age_sec:
                        logger.warning(
                            f"⚠️ TOP 50 data is STALE ({age_sec:.0f}s old, max {self.max_top50_age_sec}s) - "
                            f"skipping forgiveness (fail-open)"
                        )
                        return set()
                    
                    logger.debug(f"📊 TOP 50 freshness OK: {age_sec:.0f}s old")
                except ValueError:
                    logger.warning("⚠️ Invalid TOP 50 timestamp - skipping forgiveness")
                    return set()
            else:
                # No timestamp - use TTL as fallback check
                ttl = self.redis.ttl(self.top_50_key)
                if ttl < 0 or ttl > 3600:  # Expired or too long TTL
                    logger.warning("⚠️ TOP 50 has no timestamp and suspicious TTL - skipping")
                    return set()
            
            symbols = json.loads(data)
            
            logger.debug(f"📊 Valid TOP 50: {len(symbols)} symbols")
            return set(s.upper() for s in symbols)
            
        except Exception as e:
            logger.error(f"❌ Failed to get TOP 50: {e}")
            return set()
    
    def _get_temp_blacklist(self) -> Set[str]:
        """Get all symbols currently in temp blacklist."""
        try:
            data = self.redis.get(self.temp_blacklist_key)
            if not data:
                return set()
            
            blacklist = json.loads(data)
            symbols = set()
            
            for entry in blacklist:
                # Only include non-expired entries
                expires_at = entry.get('expires_at', 0)
                if expires_at > time.time():
                    symbols.add(entry['symbol'].upper())
            
            return symbols
            
        except Exception as e:
            logger.error(f"❌ Failed to get temp blacklist: {e}")
            return set()
    
    def _process_symbol_forgiveness(self, symbol: str) -> Dict:
        """
        Process forgiveness for a single symbol.
        
        Returns:
            Dict with action taken (FORGIVEN, COOLOFF, ERROR)
        """
        symbol = symbol.upper()
        
        # Check if symbol is in cooloff
        if self._is_in_cooloff(symbol):
            logger.info(f"⏳ {symbol}: Still in cooloff period")
            return {'symbol': symbol, 'action': 'COOLOFF', 'reason': 'cooloff_active'}
        
        # Get failure count
        failure_count = self._get_failure_count(symbol)
        
        if failure_count >= self.max_failures_before_cooloff:
            # High failure count - put on cooloff instead of forgiving
            self._set_cooloff(symbol, self.cooloff_duration_sec)
            logger.warning(
                f"⏳ {symbol}: Too many failures ({failure_count}) - "
                f"cooloff for {self.cooloff_duration_sec}s instead of forgiving"
            )
            return {
                'symbol': symbol,
                'action': 'COOLOFF',
                'reason': f'{failure_count}_failures',
                'cooloff_duration_sec': self.cooloff_duration_sec
            }
        else:
            # Normal forgiveness - remove from blacklist + reduce counter
            self._remove_from_blacklist(symbol)
            new_count = self._reduce_failure_count(symbol)
            
            logger.info(
                f"✅ {symbol}: FORGIVEN - removed from blacklist, "
                f"failures {failure_count} → {new_count} (-{self.failure_reduction_pct}%)"
            )
            return {
                'symbol': symbol,
                'action': 'FORGIVEN',
                'old_failures': failure_count,
                'new_failures': new_count,
                'reduction_pct': self.failure_reduction_pct
            }
    
    def _get_failure_count(self, symbol: str) -> int:
        """Get current failure count for symbol."""
        try:
            key = f"{self.failure_count_prefix}{symbol.upper()}"
            count = self.redis.get(key)
            return int(count) if count else 0
        except Exception as e:
            logger.debug(f"Failed to get failure count for {symbol}: {e}")
            return 0
    
    def _reduce_failure_count(self, symbol: str) -> int:
        """
        Reduce failure count by configured percentage.
        Preserves signal history instead of full reset.
        
        Returns:
            New failure count
        """
        try:
            key = f"{self.failure_count_prefix}{symbol.upper()}"
            current_count = self._get_failure_count(symbol)
            
            if current_count > 0:
                # Reduce by percentage, minimum 1 (to preserve signal)
                new_count = max(1, (current_count * self.failure_reduction_pct) // 100)
                self.redis.setex(key, 86400, new_count)  # 24h TTL
                return new_count
            return 0
        except Exception as e:
            logger.error(f"❌ Failed to reduce failure count for {symbol}: {e}")
            return current_count
    
    def _remove_from_blacklist(self, symbol: str):
        """
        Remove symbol from temp blacklist using Lua script for atomicity.
        Prevents race conditions with ZeroToleranceGatekeeper.
        """
        try:
            # Lua script for atomic blacklist removal
            # This prevents concurrent ban additions from being silently dropped
            lua_script = """
            local key = KEYS[1]
            local symbol_to_remove = ARGV[1]
            local ttl = ARGV[2]
            
            local data = redis.call('GET', key)
            if not data then
                return 0
            end
            
            local blacklist = cjson.decode(data)
            local updated_blacklist = {}
            local removed = false
            
            for i, entry in ipairs(blacklist) do
                if string.upper(entry.symbol) ~= string.upper(symbol_to_remove) then
                    table.insert(updated_blacklist, entry)
                else
                    removed = true
                end
            end
            
            if removed then
                redis.call('SETEX', key, ttl, cjson.encode(updated_blacklist))
                return 1
            end
            return 0
            """
            
            result = self.redis.eval(
                lua_script,
                1,  # Number of keys
                self.temp_blacklist_key,  # KEYS[1]
                symbol.upper(),           # ARGV[1]
                str(86400 * 2)           # ARGV[2] - 48h TTL
            )
            
            if result == 1:
                logger.debug(f"🗑️ Atomically removed {symbol} from blacklist")
            else:
                logger.debug(f"ℹ️ {symbol} not found in blacklist")
                
        except Exception as e:
            logger.error(f"❌ Failed to remove {symbol} from blacklist: {e}")
    
    def _is_in_cooloff(self, symbol: str) -> bool:
        """Check if symbol is currently in cooloff period."""
        try:
            key = f"{self.cooldown_key_prefix}{symbol.upper()}"
            return self.redis.exists(key) > 0
        except:
            return False
    
    def _set_cooloff(self, symbol: str, duration_sec: int):
        """Set cooloff period for symbol."""
        try:
            key = f"{self.cooldown_key_prefix}{symbol.upper()}"
            expires_at = time.time() + duration_sec
            self.redis.setex(key, duration_sec, expires_at)
            logger.debug(f"⏳ Set {symbol} cooloff for {duration_sec}s")
        except Exception as e:
            logger.error(f"❌ Failed to set cooloff for {symbol}: {e}")
    
    def get_stats(self) -> Dict:
        """Get forgiveness statistics for monitoring."""
        try:
            last_run = self.redis.get(self.last_run_key)
            last_run_time = float(last_run) if last_run else 0
            
            return {
                'last_run': datetime.fromtimestamp(last_run_time).isoformat() if last_run_time > 0 else None,
                'seconds_since_last_run': time.time() - last_run_time if last_run_time > 0 else None,
                'config': {
                    'max_failures_cooloff': self.max_failures_before_cooloff,
                    'cooloff_duration_sec': self.cooloff_duration_sec,
                    'failure_reduction_pct': self.failure_reduction_pct,
                    'max_top50_age_sec': self.max_top50_age_sec
                }
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


# Singleton accessor
_forgiveness_manager: Optional[BlacklistForgivenessManager] = None

def get_forgiveness_manager():
    """Get or create forgiveness manager singleton."""
    global _forgiveness_manager
    if _forgiveness_manager is None:
        from utils.redis_client import get_redis
        redis_client = get_redis()
        if not redis_client:
            logger.error("Redis not available - forgiveness manager disabled")
            return None
        _forgiveness_manager = BlacklistForgivenessManager(redis_client)
    return _forgiveness_manager
