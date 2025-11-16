# utils/zero_tolerance_gatekeeper.py
import os
import time
import logging
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("algogpt.zero_tolerance")

try:
    from utils.redis_client import get_redis
except Exception as e:
    logger.warning(f"Failed to import redis: {e}")
    get_redis = None


@dataclass
class BlockReason:
    blocked: bool
    reason: str
    symbol: str
    trade_type: str


class ZeroToleranceGatekeeper:
    def __init__(self):
        self.redis = get_redis() if get_redis else None
        
        self.top_50_key = "top50:approved_list"
        self.grid_approved_key = "grid:approved_list"
        self.temp_blacklist_key = "blacklist:temp"
        self.perm_blacklist_key = "blacklist:permanent"
        self.failure_count_key_prefix = "failures:count:"
        
        self.max_failures_before_ban = 5
        self.temp_ban_duration_hours = 24
        
        logger.info(
            "ZeroToleranceGatekeeper initialized - "
            "blocking non-TOP 100 trades, max failures: 5"
        )
    
    def check_symbol_allowed(
        self,
        symbol: str,
        trade_type: str
    ) -> BlockReason:
        symbol = symbol.upper()
        
        perm_blocked = self._is_permanently_blacklisted(symbol)
        if perm_blocked:
            return BlockReason(
                blocked=True,
                reason=f"PERMANENT BLACKLIST - symbol banned forever",
                symbol=symbol,
                trade_type=trade_type
            )
        
        temp_blocked = self._is_temp_blacklisted(symbol)
        if temp_blocked:
            return BlockReason(
                blocked=True,
                reason=f"TEMP BLACKLIST - symbol banned for {self.temp_ban_duration_hours}h",
                symbol=symbol,
                trade_type=trade_type
            )
        
        if trade_type == 'GRID':
            grid_approved = self._is_grid_approved(symbol)
            if not grid_approved:
                self._record_failure(symbol, f"GRID not approved")
                return BlockReason(
                    blocked=True,
                    reason=f"GRID NOT APPROVED - symbol not in dynamic TOP 10-30 GRID list",
                    symbol=symbol,
                    trade_type=trade_type
                )
        else:
            top_100_approved = self._is_in_top_100(symbol)
            if not top_100_approved:
                self._record_failure(symbol, f"{trade_type} not in TOP 100")
                return BlockReason(
                    blocked=True,
                    reason=f"NOT IN TOP 100 - symbol excluded from musical chairs",
                    symbol=symbol,
                    trade_type=trade_type
                )
        
        return BlockReason(
            blocked=False,
            reason="APPROVED",
            symbol=symbol,
            trade_type=trade_type
        )
    
    def _is_in_top_100(self, symbol: str) -> bool:
        if not self.redis:
            logger.warning("Redis not available, allowing trade (fail-open)")
            return True
        
        try:
            import json
            data = self.redis.get(self.top_50_key)  # Key name stays the same for backward compatibility
            if data:
                top_100_list = json.loads(data)
                # CRITICAL: Fail-open if list is empty (expired or not yet populated)
                if not top_100_list:
                    logger.warning(f"TOP 100 list EMPTY in Redis - FAIL-OPEN (expired or cold start?), allowing {symbol}")
                    return True
                return symbol.upper() in [s.upper() for s in top_100_list]
            else:
                logger.warning(f"TOP 100 list not found in Redis - FAIL-OPEN (cold start?), allowing {symbol}")
                return True
        except Exception as e:
            logger.warning(f"Failed to check TOP 100: {e}, allowing trade (fail-open)")
            return True
    
    def _is_grid_approved(self, symbol: str) -> bool:
        if not self.redis:
            logger.warning("Redis not available, allowing GRID (fail-open)")
            return True
        
        try:
            import json
            data = self.redis.get(self.grid_approved_key)
            if data:
                grid_list = json.loads(data)
                # CRITICAL: Fail-open if list is empty (expired or not yet populated)
                if not grid_list:
                    logger.warning(f"GRID approved list EMPTY in Redis - FAIL-OPEN (expired or cold start?), allowing {symbol}")
                    return True
                return symbol.upper() in [s.upper() for s in grid_list]
            else:
                logger.warning(f"GRID approved list not found in Redis - FAIL-OPEN (cold start?), allowing {symbol}")
                return True
        except Exception as e:
            logger.warning(f"Failed to check GRID approved: {e}, allowing trade (fail-open)")
            return True
    
    def _is_permanently_blacklisted(self, symbol: str) -> bool:
        if not self.redis:
            return False
        
        try:
            import json
            data = self.redis.get(self.perm_blacklist_key)
            if data:
                perm_list = json.loads(data)
                return symbol.upper() in [s.upper() for s in perm_list]
        except Exception as e:
            logger.warning(f"Failed to check permanent blacklist: {e}")
            return False
        
        return False
    
    def _is_temp_blacklisted(self, symbol: str) -> bool:
        if not self.redis:
            return False
        
        try:
            import json
            
            self._cleanup_expired_blacklist()
            
            data = self.redis.get(self.temp_blacklist_key)
            if data:
                temp_list = json.loads(data)
                for item in temp_list:
                    if item['symbol'].upper() == symbol.upper():
                        expires_at = item.get('expires_at', 0)
                        if expires_at > time.time():
                            return True
        except Exception as e:
            logger.warning(f"Failed to check temp blacklist: {e}")
            return False
        
        return False
    
    def _cleanup_expired_blacklist(self):
        """Auto-clean expired symbols from temp blacklist"""
        if not self.redis:
            return
        
        try:
            import json
            data = self.redis.get(self.temp_blacklist_key)
            if not data:
                return
            
            temp_list = json.loads(data)
            current_time = time.time()
            
            active_list = [
                item for item in temp_list
                if item.get('expires_at', 0) > current_time
            ]
            
            if len(active_list) < len(temp_list):
                removed_count = len(temp_list) - len(active_list)
                logger.info(
                    f"🧹 Auto-cleaned {removed_count} expired symbols from temp blacklist "
                    f"({len(active_list)} active remain)"
                )
                
                if active_list:
                    self.redis.setex(
                        self.temp_blacklist_key,
                        86400 * 2,
                        json.dumps(active_list)
                    )
                else:
                    self.redis.delete(self.temp_blacklist_key)
                    logger.info("✅ Temp blacklist completely cleared (all expired)")
                    
        except Exception as e:
            logger.warning(f"Failed to cleanup expired blacklist: {e}")
    
    def _record_failure(self, symbol: str, reason: str):
        if not self.redis:
            return
        
        try:
            failure_key = f"{self.failure_count_key_prefix}{symbol.upper()}"
            
            count = self.redis.incr(failure_key)
            self.redis.expire(failure_key, 86400)
            
            logger.warning(
                f"❌ FAILURE #{count} for {symbol}: {reason}"
            )
            
            if count >= self.max_failures_before_ban:
                self._add_to_temp_blacklist(symbol, reason)
                
        except Exception as e:
            logger.error(f"Failed to record failure for {symbol}: {e}")
    
    def _add_to_temp_blacklist(self, symbol: str, reason: str):
        if not self.redis:
            return
        
        try:
            import json
            
            self._cleanup_expired_blacklist()
            
            data = self.redis.get(self.temp_blacklist_key)
            temp_list = json.loads(data) if data else []
            
            if any(item['symbol'].upper() == symbol.upper() for item in temp_list):
                logger.warning(f"⚠️ {symbol} already in temp blacklist, skipping duplicate")
                return
            
            expires_at = time.time() + (self.temp_ban_duration_hours * 3600)
            
            temp_list.append({
                'symbol': symbol.upper(),
                'reason': reason,
                'added_at': time.time(),
                'expires_at': expires_at,
                'expires_human': datetime.fromtimestamp(expires_at).isoformat()
            })
            
            self.redis.setex(
                self.temp_blacklist_key,
                86400 * 2,
                json.dumps(temp_list)
            )
            
            logger.error(
                f"🚫 TEMP BLACKLIST: {symbol} banned for {self.temp_ban_duration_hours}h | "
                f"Reason: {reason} | Active bans: {len(temp_list)}"
            )
            
        except Exception as e:
            logger.error(f"Failed to add {symbol} to temp blacklist: {e}")
    
    def add_to_permanent_blacklist(self, symbol: str, reason: str):
        if not self.redis:
            return
        
        try:
            import json
            
            data = self.redis.get(self.perm_blacklist_key)
            perm_list = json.loads(data) if data else []
            
            if symbol.upper() not in [s.upper() for s in perm_list]:
                perm_list.append(symbol.upper())
            
            self.redis.set(self.perm_blacklist_key, json.dumps(perm_list))
            
            logger.error(
                f"💀 PERMANENT BLACKLIST: {symbol} banned forever | "
                f"Reason: {reason}"
            )
            
        except Exception as e:
            logger.error(f"Failed to add {symbol} to permanent blacklist: {e}")
    
    def get_top_100_list(self) -> List[str]:
        if not self.redis:
            return []
        
        try:
            import json
            data = self.redis.get(self.top_50_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Failed to get TOP 100 list: {e}")
        
        return []
    
    def get_grid_approved_list(self) -> List[str]:
        if not self.redis:
            return []
        
        try:
            import json
            data = self.redis.get(self.grid_approved_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"Failed to get GRID approved list: {e}")
        
        return []
    
    def get_blacklist_status(self) -> Dict[str, Any]:
        perm_list = []
        temp_list = []
        
        if self.redis:
            try:
                import json
                
                data = self.redis.get(self.perm_blacklist_key)
                if data:
                    perm_list = json.loads(data)
                
                data = self.redis.get(self.temp_blacklist_key)
                if data:
                    temp_raw = json.loads(data)
                    now = time.time()
                    temp_list = [
                        item for item in temp_raw
                        if item.get('expires_at', 0) > now
                    ]
            except Exception as e:
                logger.warning(f"Failed to get blacklist status: {e}")
        
        return {
            'permanent': perm_list,
            'temporary': temp_list,
            'permanent_count': len(perm_list),
            'temporary_count': len(temp_list)
        }


def get_gatekeeper() -> ZeroToleranceGatekeeper:
    """
    Creates a NEW instance every time to ensure fresh Redis data.
    
    CRITICAL: No caching! This ensures that blacklist changes in Redis
    are immediately reflected in all workers without needing restarts.
    """
    return ZeroToleranceGatekeeper()
