"""
Trading Gatekeeper - Unified pre-trade validation gate

Integrates all filtering systems:
- Symbol Filter Engine (volume, liquidity, whitelist)
- Order Quality Monitor (fill rate, slippage)
- Position Limits Manager (positions, orders, exposure)
- Dynamic Leverage System (confidence, safety)

Provides single validation entry point for all trades.

Environment Variables:
- TRADING_GATEKEEPER_ENABLED: Enable gatekeeper (default: 1)
- GATEKEEPER_FAIL_MODE: open/closed - behavior on check failure (default: open)
"""

import os
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger("algogpt.gatekeeper")

# Configuration
TRADING_GATEKEEPER_ENABLED = os.getenv("TRADING_GATEKEEPER_ENABLED", "1") == "1"
GATEKEEPER_FAIL_MODE = os.getenv("GATEKEEPER_FAIL_MODE", "open").lower()  # open/closed


@dataclass
class ValidationResult:
    """Complete validation result"""
    approved: bool
    symbol: str
    reason: str = ""
    leverage: Optional[int] = None
    max_position_size: Optional[float] = None
    filters_passed: List[str] = field(default_factory=list)
    filters_failed: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


class TradingGatekeeper:
    """
    Unified pre-trade validation system
    
    Validates all aspects of a trade before execution:
    1. Symbol filtering (market cap, volume, liquidity)
    2. Order quality (fill rate, slippage history)
    3. Position limits (max positions, exposure)
    4. Dynamic leverage calculation
    
    Provides single approval/rejection decision.
    """
    
    def __init__(self):
        self.enabled = TRADING_GATEKEEPER_ENABLED
        self.fail_mode = GATEKEEPER_FAIL_MODE
        
        # Import filter systems
        try:
            from utils.symbol_filter import get_symbol_filter, SymbolFilterEngine
            self.symbol_filter: Optional[SymbolFilterEngine] = get_symbol_filter()
            self._symbol_filter_available = True
        except Exception as e:
            logger.warning(f"Symbol filter unavailable: {e}")
            self.symbol_filter = None
            self._symbol_filter_available = False
        
        try:
            from utils.order_quality_monitor import get_quality_monitor, OrderQualityMonitor
            self.quality_monitor: Optional[OrderQualityMonitor] = get_quality_monitor()
            self._quality_monitor_available = True
        except Exception as e:
            logger.warning(f"Quality monitor unavailable: {e}")
            self.quality_monitor = None
            self._quality_monitor_available = False
        
        try:
            from utils.position_limits import get_limits_manager, PositionLimitsManager
            self.limits_manager: Optional[PositionLimitsManager] = get_limits_manager()
            self._limits_manager_available = True
        except Exception as e:
            logger.warning(f"Limits manager unavailable: {e}")
            self.limits_manager = None
            self._limits_manager_available = False
        
        try:
            from utils.dynamic_leverage import get_dynamic_leverage_calculator, DynamicLeverageCalculator
            self.leverage_engine: Optional[DynamicLeverageCalculator] = get_dynamic_leverage_calculator()
            self._leverage_engine_available = True
        except Exception as e:
            logger.warning(f"Dynamic leverage unavailable: {e}")
            self.leverage_engine = None
            self._leverage_engine_available = False
        
        try:
            from utils.zero_tolerance_gatekeeper import get_gatekeeper, ZeroToleranceGatekeeper
            self.zero_tolerance: Optional[ZeroToleranceGatekeeper] = get_gatekeeper()
            self._zero_tolerance_available = True
        except Exception as e:
            logger.warning(f"Zero Tolerance Gatekeeper unavailable: {e}")
            self.zero_tolerance = None
            self._zero_tolerance_available = False
        
        logger.info(
            f"🚪 Trading Gatekeeper initialized | "
            f"Enabled: {self.enabled} | "
            f"Fail Mode: {self.fail_mode} | "
            f"Filters: Symbol={self._symbol_filter_available}, "
            f"Quality={self._quality_monitor_available}, "
            f"Limits={self._limits_manager_available}, "
            f"Leverage={self._leverage_engine_available}, "
            f"ZeroTolerance={self._zero_tolerance_available}"
        )
    
    def validate_trade(
        self,
        symbol: str,
        order_type: str = "NEW",
        trade_quality: Optional[float] = None,
        atr_pct: Optional[float] = None,
        current_price: Optional[float] = None,
        **kwargs
    ) -> ValidationResult:
        """
        Main validation entry point
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            order_type: NEW/CLOSE/MODIFY
            trade_quality: AI trade quality score (0-10)
            atr_pct: ATR percentage for leverage calculation
            current_price: Current symbol price
            **kwargs: Additional context
        
        Returns:
            ValidationResult with approval/rejection decision
        """
        if not self.enabled:
            return ValidationResult(
                approved=True,
                symbol=symbol,
                reason="Gatekeeper disabled",
                details={"gatekeeper_enabled": False}
            )
        
        symbol = symbol.upper()
        result = ValidationResult(approved=True, symbol=symbol)
        
        # Run all validation checks
        try:
            # 0. ZERO TOLERANCE GATEKEEPER (TOP 50 FILTER) - HIGHEST PRIORITY
            if self._zero_tolerance_available:
                # Accept both position_type and position_side (ExecutionBot uses position_side)
                trade_type = kwargs.get("position_type") or kwargs.get("position_side") or kwargs.get("trade_type") or "LONG"
                trade_type = str(trade_type).upper()
                
                # Normalize GRID detection
                is_grid = kwargs.get("is_grid", False) or "GRID" in trade_type
                if is_grid:
                    trade_type = "GRID"
                
                block_result = self.zero_tolerance.check_symbol_allowed(symbol, trade_type)
                result.filters_passed.append("zero_tolerance") if not block_result.blocked else result.filters_failed.append("zero_tolerance")
                
                if block_result.blocked:
                    logger.warning(
                        f"🚫 ZERO TOLERANCE BLOCK: {symbol} ({trade_type}) - {block_result.reason}"
                    )
                    return self._build_rejection(result, "zero_tolerance", block_result.reason)
            
            # 1. SYMBOL FILTER
            if self._symbol_filter_available:
                symbol_check = self._run_symbol_filter(symbol, **kwargs)
                result.filters_passed.append("symbol_filter") if symbol_check[0] else result.filters_failed.append("symbol_filter")
                if not symbol_check[0]:
                    return self._build_rejection(result, "symbol_filter", symbol_check[1])
            
            # 2. ORDER QUALITY CHECK
            if self._quality_monitor_available:
                quality_check = self._run_quality_check(symbol)
                result.filters_passed.append("order_quality") if quality_check[0] else result.filters_failed.append("order_quality")
                if not quality_check[0]:
                    # Quality check is a warning, not a hard block
                    result.warnings.append(f"Order quality: {quality_check[1]}")
            
            # 3. POSITION LIMITS
            if self._limits_manager_available:
                limits_check = self._run_limits_check(symbol, order_type, **kwargs)
                result.filters_passed.append("position_limits") if limits_check[0] else result.filters_failed.append("position_limits")
                if not limits_check[0]:
                    return self._build_rejection(result, "position_limits", limits_check[1])
            
            # 4. DYNAMIC LEVERAGE (if quality score provided)
            if self._leverage_engine_available and trade_quality is not None:
                leverage_result = self._run_leverage_calculation(
                    symbol=symbol,
                    trade_quality=trade_quality,
                    atr_pct=atr_pct,
                    current_price=current_price,
                    **kwargs
                )
                result.leverage = leverage_result.get("leverage")
                result.max_position_size = leverage_result.get("position_size")
                result.details["leverage_reasoning"] = leverage_result.get("reasoning")
                result.filters_passed.append("dynamic_leverage")
            
            # All checks passed
            result.approved = True
            result.reason = "All validation checks passed"
            result.details.update({
                "filters_passed": result.filters_passed,
                "warnings": result.warnings if result.warnings else None
            })
            
            logger.info(
                f"✅ {symbol}: APPROVED | "
                f"Filters: {len(result.filters_passed)} passed | "
                f"Warnings: {len(result.warnings)} | "
                f"Leverage: {result.leverage}x"
            )
            
            return result
        
        except Exception as e:
            logger.error(f"❌ {symbol}: Validation error: {e}")
            
            # Fail mode behavior
            if self.fail_mode == "closed":
                # Fail-closed: reject on error
                result.approved = False
                result.reason = f"Validation error (fail-closed): {e}"
                return result
            else:
                # Fail-open: allow on error
                result.approved = True
                result.reason = f"Validation error (fail-open, allowed): {e}"
                result.warnings.append(f"Validation error: {e}")
                return result
    
    def _run_symbol_filter(self, symbol: str, **kwargs) -> Tuple[bool, str]:
        """Run symbol filter validation"""
        try:
            if self.symbol_filter is None:
                return self._fail_mode_behavior("Symbol filter not available")
            filter_result = self.symbol_filter.validate_symbol(symbol, **kwargs)
            return filter_result.passed, filter_result.reason
        except Exception as e:
            logger.error(f"❌ Symbol filter error: {e}")
            return self._fail_mode_behavior(f"Symbol filter error: {e}")
    
    def _run_quality_check(self, symbol: str) -> Tuple[bool, str]:
        """Run order quality check"""
        try:
            if self.quality_monitor is None:
                return self._fail_mode_behavior("Quality monitor not available")
            passed, reason = self.quality_monitor.passes_quality_check(symbol)
            return passed, reason
        except Exception as e:
            logger.error(f"❌ Quality check error: {e}")
            return self._fail_mode_behavior(f"Quality check error: {e}")
    
    def _run_limits_check(self, symbol: str, order_type: str, **kwargs) -> Tuple[bool, str]:
        """Run position limits check"""
        try:
            if self.limits_manager is None:
                return self._fail_mode_behavior("Limits manager not available")
            limits_result = self.limits_manager.check_limits(symbol, order_type, **kwargs)
            return limits_result.passed, limits_result.reason
        except Exception as e:
            logger.error(f"❌ Limits check error: {e}")
            return self._fail_mode_behavior(f"Limits check error: {e}")
    
    def _run_leverage_calculation(
        self,
        symbol: str,
        trade_quality: float,
        atr_pct: Optional[float],
        current_price: Optional[float],
        **kwargs
    ) -> Dict[str, Any]:
        """Run dynamic leverage calculation"""
        try:
            if self.leverage_engine is None:
                return {
                    "leverage": 5,
                    "position_size": 0.01,
                    "reasoning": "Leverage engine not available (default)"
                }
            leverage_result = self.leverage_engine.calculate_leverage(
                trade_quality=trade_quality,
                symbol=symbol,
                atr_pct=atr_pct or 0.02,  # Default 2% if not provided
                current_price=current_price or 0.0,
                **kwargs
            )
            return leverage_result
        except Exception as e:
            logger.error(f"❌ Leverage calculation error: {e}")
            # Return safe defaults
            return {
                "leverage": 5,
                "position_size": 0.01,
                "reasoning": f"Error in calculation (default): {e}"
            }
    
    def _fail_mode_behavior(self, error_msg: str) -> Tuple[bool, str]:
        """Determine behavior based on fail mode"""
        if self.fail_mode == "closed":
            return False, error_msg
        else:
            return True, f"{error_msg} (allowed)"
    
    def _build_rejection(
        self,
        result: ValidationResult,
        failed_filter: str,
        reason: str
    ) -> ValidationResult:
        """Build rejection result"""
        result.approved = False
        result.reason = f"Failed {failed_filter}: {reason}"
        result.details["failed_filter"] = failed_filter
        result.details["filters_passed"] = result.filters_passed
        result.details["filters_failed"] = result.filters_failed
        
        logger.warning(
            f"🚫 {result.symbol}: REJECTED | "
            f"Filter: {failed_filter} | "
            f"Reason: {reason}"
        )
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get gatekeeper statistics"""
        stats = {
            "enabled": self.enabled,
            "fail_mode": self.fail_mode,
            "filters_available": {
                "symbol_filter": self._symbol_filter_available,
                "quality_monitor": self._quality_monitor_available,
                "limits_manager": self._limits_manager_available,
                "leverage_engine": self._leverage_engine_available
            }
        }
        
        # Add individual filter stats
        if self._symbol_filter_available and self.symbol_filter:
            stats["symbol_filter"] = self.symbol_filter.get_stats()
        
        if self._quality_monitor_available and self.quality_monitor:
            stats["quality_monitor"] = self.quality_monitor.get_stats()
        
        if self._limits_manager_available and self.limits_manager:
            stats["limits_manager"] = self.limits_manager.get_stats()
        
        if self._leverage_engine_available and self.leverage_engine:
            stats["leverage_engine"] = self.leverage_engine.get_leverage_stats()
        
        return stats


# Singleton instance
_gatekeeper: Optional[TradingGatekeeper] = None


def get_gatekeeper() -> TradingGatekeeper:
    """Get or create singleton gatekeeper"""
    global _gatekeeper
    if _gatekeeper is None:
        _gatekeeper = TradingGatekeeper()
    return _gatekeeper


# Convenience function
def validate_trade(symbol: str, **kwargs) -> ValidationResult:
    """Quick trade validation"""
    gatekeeper = get_gatekeeper()
    return gatekeeper.validate_trade(symbol, **kwargs)


# Public API
__all__ = [
    "TradingGatekeeper",
    "ValidationResult",
    "get_gatekeeper",
    "validate_trade"
]
