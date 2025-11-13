"""
Position Limits Manager - Control position and order exposure

Enforces:
- Max positions per symbol
- Max total open orders
- Correlation exposure limits
- Portfolio concentration limits

Environment Variables:
- POSITION_LIMITS_ENABLED: Enable limits (default: 1)
- MAX_POSITIONS_PER_SYMBOL: Max positions per symbol (default: 2)
- MAX_TOTAL_OPEN_ORDERS: Max total open orders (default: 25)
- MAX_CORRELATED_EXPOSURE: Max exposure to correlated assets (default: 0.3 = 30%)
- MAX_SINGLE_SYMBOL_EXPOSURE: Max % of portfolio in one symbol (default: 0.15 = 15%)
"""

import os
import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger("algogpt.position_limits")

# Configuration
POSITION_LIMITS_ENABLED = os.getenv("POSITION_LIMITS_ENABLED", "1") == "1"
MAX_POSITIONS_PER_SYMBOL = int(os.getenv("MAX_POSITIONS_PER_SYMBOL", "2"))
MAX_TOTAL_OPEN_ORDERS = int(os.getenv("MAX_TOTAL_OPEN_ORDERS", "25"))
MAX_CORRELATED_EXPOSURE = float(os.getenv("MAX_CORRELATED_EXPOSURE", "0.30"))  # 30%
MAX_SINGLE_SYMBOL_EXPOSURE = float(os.getenv("MAX_SINGLE_SYMBOL_EXPOSURE", "0.15"))  # 15%

# Symbol correlation groups (assets that tend to move together)
CORRELATION_GROUPS = {
    "BTC_ECOSYSTEM": {"BTCUSDT"},
    "ETH_ECOSYSTEM": {"ETHUSDT", "STETHUSDT"},
    "LAYER1": {"SOLUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT"},
    "LAYER2": {"ARBUSDT", "OPUSDT", "STRKUSDT", "ZKUSDT", "METISUSDT"},
    "DEFI": {"AAVEUSDT", "UNIUSDT", "LINKUSDT", "MKRUSDT", "COMPUSDT", "SUSHIUSDT"},
    "MEME": {"DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT"},
    "AI": {"FETUSDT", "AGIXUSDT", "OCEANUSDT", "RNDRUSDT", "TAOUSDT"},
    "GAMING": {"SANDUSDT", "MANAUSDT", "AXSUSDT", "GALAUSDT", "ENJUSDT"},
}


@dataclass
class LimitCheckResult:
    """Result of limit check"""
    passed: bool
    symbol: str
    reason: str = ""
    details: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class PositionLimitsManager:
    """
    Manage and enforce position/order limits
    
    Prevents over-exposure to single symbols or correlated groups
    """
    
    def __init__(self):
        self.enabled = POSITION_LIMITS_ENABLED
        
        logger.info(
            f"🛡️ Position Limits Manager initialized | "
            f"Enabled: {self.enabled} | "
            f"Max per symbol: {MAX_POSITIONS_PER_SYMBOL} | "
            f"Max total orders: {MAX_TOTAL_OPEN_ORDERS}"
        )
    
    def check_limits(
        self,
        symbol: str,
        order_type: str = "NEW",
        **kwargs
    ) -> LimitCheckResult:
        """
        Main limit check entry point
        
        Args:
            symbol: Trading symbol
            order_type: NEW (opening), CLOSE (closing), MODIFY (modifying)
            **kwargs: Additional context
        
        Returns:
            LimitCheckResult with passed/failed status
        """
        if not self.enabled:
            return LimitCheckResult(passed=True, symbol=symbol, reason="Limits disabled")
        
        symbol = symbol.upper()
        
        # Closing orders always allowed
        if order_type == "CLOSE":
            return LimitCheckResult(passed=True, symbol=symbol, reason="Closing order allowed")
        
        # 1. Check positions per symbol
        positions_result = self._check_positions_per_symbol(symbol)
        if not positions_result.passed:
            return positions_result
        
        # 2. Check total open orders
        orders_result = self._check_total_open_orders()
        if not orders_result.passed:
            return orders_result
        
        # 3. Check correlation exposure
        correlation_result = self._check_correlation_exposure(symbol, **kwargs)
        if not correlation_result.passed:
            return correlation_result
        
        # 4. Check single symbol exposure
        exposure_result = self._check_single_symbol_exposure(symbol, **kwargs)
        if not exposure_result.passed:
            return exposure_result
        
        # All checks passed
        return LimitCheckResult(
            passed=True,
            symbol=symbol,
            reason="All limit checks passed",
            details={
                "positions_check": "passed",
                "orders_check": "passed",
                "correlation_check": "passed",
                "exposure_check": "passed"
            }
        )
    
    def _check_positions_per_symbol(self, symbol: str) -> LimitCheckResult:
        """Check if symbol has too many open positions"""
        try:
            from utils.binance_client import get_open_positions
            
            positions = get_open_positions(symbol)
            open_positions = [
                p for p in positions
                if float(p.get("positionAmt", 0)) != 0
            ]
            
            count = len(open_positions)
            
            if count >= MAX_POSITIONS_PER_SYMBOL:
                logger.warning(
                    f"⚠️ {symbol}: Max positions reached {count}/{MAX_POSITIONS_PER_SYMBOL}"
                )
                return LimitCheckResult(
                    passed=False,
                    symbol=symbol,
                    reason=f"Max positions per symbol reached ({count}/{MAX_POSITIONS_PER_SYMBOL})",
                    details={
                        "current_positions": count,
                        "max_allowed": MAX_POSITIONS_PER_SYMBOL
                    }
                )
            
            return LimitCheckResult(passed=True, symbol=symbol)
        
        except Exception as e:
            logger.error(f"❌ {symbol}: Position check failed: {e}")
            # Fail-open: allow if can't check
            return LimitCheckResult(passed=True, symbol=symbol, reason=f"Check failed (allowed): {e}")
    
    def _check_total_open_orders(self) -> LimitCheckResult:
        """Check total open orders across all symbols"""
        try:
            from utils.binance_client import get_open_orders
            
            orders = get_open_orders()
            count = len(orders)
            
            if count >= MAX_TOTAL_OPEN_ORDERS:
                logger.warning(
                    f"⚠️ Max total orders reached {count}/{MAX_TOTAL_OPEN_ORDERS}"
                )
                return LimitCheckResult(
                    passed=False,
                    symbol="ALL",
                    reason=f"Max total orders reached ({count}/{MAX_TOTAL_OPEN_ORDERS})",
                    details={
                        "current_orders": count,
                        "max_allowed": MAX_TOTAL_OPEN_ORDERS
                    }
                )
            
            return LimitCheckResult(passed=True, symbol="ALL")
        
        except Exception as e:
            logger.error(f"❌ Total orders check failed: {e}")
            # Fail-open: allow if can't check
            return LimitCheckResult(passed=True, symbol="ALL", reason=f"Check failed (allowed): {e}")
    
    def _check_correlation_exposure(
        self,
        symbol: str,
        **kwargs
    ) -> LimitCheckResult:
        """Check exposure to correlated assets"""
        try:
            # Find correlation group
            group_name = None
            for name, symbols in CORRELATION_GROUPS.items():
                if symbol in symbols:
                    group_name = name
                    break
            
            if not group_name:
                # Not in any correlation group
                return LimitCheckResult(passed=True, symbol=symbol)
            
            # Get portfolio value
            portfolio_value = self._get_portfolio_value()
            if portfolio_value == 0:
                return LimitCheckResult(passed=True, symbol=symbol)
            
            # Calculate exposure to correlated group
            group_exposure = self._calculate_group_exposure(
                CORRELATION_GROUPS[group_name]
            )
            
            exposure_pct = group_exposure / portfolio_value
            
            if exposure_pct >= MAX_CORRELATED_EXPOSURE:
                logger.warning(
                    f"⚠️ {symbol}: High correlation exposure {exposure_pct*100:.1f}% "
                    f"to {group_name} (max: {MAX_CORRELATED_EXPOSURE*100:.0f}%)"
                )
                return LimitCheckResult(
                    passed=False,
                    symbol=symbol,
                    reason=f"High exposure to {group_name} group ({exposure_pct*100:.1f}%)",
                    details={
                        "group": group_name,
                        "current_exposure_pct": f"{exposure_pct*100:.1f}%",
                        "max_allowed_pct": f"{MAX_CORRELATED_EXPOSURE*100:.0f}%",
                        "group_symbols": list(CORRELATION_GROUPS[group_name])
                    }
                )
            
            return LimitCheckResult(passed=True, symbol=symbol)
        
        except Exception as e:
            logger.error(f"❌ {symbol}: Correlation check failed: {e}")
            # Fail-open: allow if can't check
            return LimitCheckResult(passed=True, symbol=symbol, reason=f"Check failed (allowed): {e}")
    
    def _check_single_symbol_exposure(
        self,
        symbol: str,
        **kwargs
    ) -> LimitCheckResult:
        """Check if single symbol exposure is too high"""
        try:
            portfolio_value = self._get_portfolio_value()
            if portfolio_value == 0:
                return LimitCheckResult(passed=True, symbol=symbol)
            
            symbol_exposure = self._get_symbol_exposure(symbol)
            exposure_pct = symbol_exposure / portfolio_value
            
            if exposure_pct >= MAX_SINGLE_SYMBOL_EXPOSURE:
                logger.warning(
                    f"⚠️ {symbol}: High single symbol exposure {exposure_pct*100:.1f}% "
                    f"(max: {MAX_SINGLE_SYMBOL_EXPOSURE*100:.0f}%)"
                )
                return LimitCheckResult(
                    passed=False,
                    symbol=symbol,
                    reason=f"High single symbol exposure ({exposure_pct*100:.1f}%)",
                    details={
                        "current_exposure_pct": f"{exposure_pct*100:.1f}%",
                        "max_allowed_pct": f"{MAX_SINGLE_SYMBOL_EXPOSURE*100:.0f}%"
                    }
                )
            
            return LimitCheckResult(passed=True, symbol=symbol)
        
        except Exception as e:
            logger.error(f"❌ {symbol}: Exposure check failed: {e}")
            # Fail-open: allow if can't check
            return LimitCheckResult(passed=True, symbol=symbol, reason=f"Check failed (allowed): {e}")
    
    def _get_portfolio_value(self) -> float:
        """Get total portfolio value"""
        try:
            from utils.binance_client import futures_balance
            
            balances = futures_balance()
            total = sum(
                float(b.get("balance", 0))
                for b in balances
                if b.get("asset") == "USDT"
            )
            return total
        except Exception:
            return 0.0
    
    def _get_symbol_exposure(self, symbol: str) -> float:
        """Get current exposure to symbol (USDT value)"""
        try:
            from utils.binance_client import get_open_positions
            
            positions = get_open_positions(symbol)
            total_exposure = 0.0
            
            for pos in positions:
                notional = abs(float(pos.get("notional", 0)))
                total_exposure += notional
            
            return total_exposure
        except Exception:
            return 0.0
    
    def _calculate_group_exposure(self, symbols: Set[str]) -> float:
        """Calculate total exposure to a group of symbols"""
        total = 0.0
        for symbol in symbols:
            total += self._get_symbol_exposure(symbol)
        return total
    
    def get_stats(self) -> Dict[str, Any]:
        """Get limit statistics"""
        try:
            from utils.binance_client import get_open_positions, get_open_orders
            
            positions = get_open_positions()
            orders = get_open_orders()
            
            # Count positions per symbol
            positions_by_symbol = {}
            for pos in positions:
                if float(pos.get("positionAmt", 0)) == 0:
                    continue
                symbol = pos.get("symbol", "")
                positions_by_symbol[symbol] = positions_by_symbol.get(symbol, 0) + 1
            
            return {
                "enabled": self.enabled,
                "total_open_positions": len([p for p in positions if float(p.get("positionAmt", 0)) != 0]),
                "total_open_orders": len(orders),
                "symbols_with_positions": len(positions_by_symbol),
                "max_positions_per_symbol": MAX_POSITIONS_PER_SYMBOL,
                "max_total_orders": MAX_TOTAL_OPEN_ORDERS,
                "limits": {
                    "positions_per_symbol": f"{MAX_POSITIONS_PER_SYMBOL}",
                    "total_orders": f"{MAX_TOTAL_OPEN_ORDERS}",
                    "correlated_exposure": f"{MAX_CORRELATED_EXPOSURE*100:.0f}%",
                    "single_symbol_exposure": f"{MAX_SINGLE_SYMBOL_EXPOSURE*100:.0f}%"
                }
            }
        except Exception as e:
            logger.error(f"❌ Stats failed: {e}")
            return {"error": str(e)}


# Singleton instance
_limits_manager: Optional[PositionLimitsManager] = None


def get_limits_manager() -> PositionLimitsManager:
    """Get or create singleton limits manager"""
    global _limits_manager
    if _limits_manager is None:
        _limits_manager = PositionLimitsManager()
    return _limits_manager


# Convenience function
def check_position_limits(symbol: str, **kwargs) -> LimitCheckResult:
    """Quick limit check"""
    manager = get_limits_manager()
    return manager.check_limits(symbol, **kwargs)


# Public API
__all__ = [
    "PositionLimitsManager",
    "LimitCheckResult",
    "get_limits_manager",
    "check_position_limits",
    "CORRELATION_GROUPS"
]
