"""
Order Quality Monitor - Track order execution performance

Monitors:
- Fill Rate: % of orders that successfully fill
- Slippage: Difference between expected and actual fill price
- Execution Speed: Time from order placement to fill
- Order rejection rate

Environment Variables:
- ORDER_QUALITY_ENABLED: Enable monitoring (default: 1)
- MIN_FILL_RATE: Minimum acceptable fill rate (default: 0.65 = 65%)
- MAX_AVG_SLIPPAGE: Maximum acceptable slippage (default: 0.02 = 2%)
- SLIPPAGE_ALERT_THRESHOLD: Alert if slippage exceeds (default: 0.03 = 3%)
"""

import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger("algogpt.order_quality")

# Configuration
ORDER_QUALITY_ENABLED = os.getenv("ORDER_QUALITY_ENABLED", "1") == "1"
MIN_FILL_RATE = float(os.getenv("MIN_FILL_RATE", "0.65"))  # 65%
MAX_AVG_SLIPPAGE = float(os.getenv("MAX_AVG_SLIPPAGE", "0.02"))  # 2%
SLIPPAGE_ALERT_THRESHOLD = float(os.getenv("SLIPPAGE_ALERT_THRESHOLD", "0.03"))  # 3%
QUALITY_LOOKBACK_HOURS = int(os.getenv("QUALITY_LOOKBACK_HOURS", "24"))


@dataclass
class OrderRecord:
    """Single order execution record"""
    symbol: str
    order_id: str
    side: str  # BUY/SELL
    order_type: str  # LIMIT/MARKET
    requested_price: Optional[float]
    filled_price: Optional[float]
    requested_qty: float
    filled_qty: float
    status: str  # FILLED/PARTIALLY_FILLED/CANCELED/REJECTED
    placed_at: datetime
    filled_at: Optional[datetime] = None
    
    @property
    def slippage(self) -> Optional[float]:
        """Calculate slippage percentage"""
        if not self.requested_price or not self.filled_price:
            return None
        
        # Positive slippage = worse execution
        # BUY: paid more than expected
        # SELL: got less than expected
        if self.side == "BUY":
            slip = (self.filled_price - self.requested_price) / self.requested_price
        else:  # SELL
            slip = (self.requested_price - self.filled_price) / self.requested_price
        
        return slip
    
    @property
    def fill_rate(self) -> float:
        """Calculate fill rate for this order"""
        if self.requested_qty == 0:
            return 0.0
        return self.filled_qty / self.requested_qty
    
    @property
    def execution_time_ms(self) -> Optional[int]:
        """Time from placement to fill (milliseconds)"""
        if not self.filled_at:
            return None
        delta = self.filled_at - self.placed_at
        return int(delta.total_seconds() * 1000)


@dataclass
class SymbolQualityMetrics:
    """Quality metrics for a symbol"""
    symbol: str
    total_orders: int = 0
    filled_orders: int = 0
    rejected_orders: int = 0
    canceled_orders: int = 0
    total_slippage: float = 0.0
    slippage_count: int = 0
    total_fill_rate: float = 0.0
    execution_times: List[int] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)
    
    @property
    def fill_rate(self) -> float:
        """Overall fill rate for symbol"""
        if self.total_orders == 0:
            return 0.0
        return self.filled_orders / self.total_orders
    
    @property
    def avg_slippage(self) -> float:
        """Average slippage for symbol"""
        if self.slippage_count == 0:
            return 0.0
        return self.total_slippage / self.slippage_count
    
    @property
    def avg_execution_time_ms(self) -> float:
        """Average execution time in milliseconds"""
        if not self.execution_times:
            return 0.0
        return sum(self.execution_times) / len(self.execution_times)
    
    @property
    def rejection_rate(self) -> float:
        """Order rejection rate"""
        if self.total_orders == 0:
            return 0.0
        return self.rejected_orders / self.total_orders


class OrderQualityMonitor:
    """
    Monitor and track order execution quality
    
    Tracks fill rate, slippage, and execution speed per symbol
    """
    
    def __init__(self):
        self.enabled = ORDER_QUALITY_ENABLED
        self.symbol_metrics: Dict[str, SymbolQualityMetrics] = {}
        self.order_history: List[OrderRecord] = []
        self.max_history = 1000  # Keep last 1000 orders
        
        logger.info(
            f"📊 Order Quality Monitor initialized | "
            f"Enabled: {self.enabled} | "
            f"Min Fill Rate: {MIN_FILL_RATE*100:.0f}% | "
            f"Max Slippage: {MAX_AVG_SLIPPAGE*100:.1f}%"
        )
    
    def record_order(
        self,
        symbol: str,
        order_id: str,
        side: str,
        order_type: str,
        requested_price: Optional[float],
        filled_price: Optional[float],
        requested_qty: float,
        filled_qty: float,
        status: str,
        placed_at: Optional[datetime] = None,
        filled_at: Optional[datetime] = None
    ) -> None:
        """
        Record an order execution
        
        Args:
            symbol: Trading symbol
            order_id: Binance order ID
            side: BUY or SELL
            order_type: LIMIT or MARKET
            requested_price: Intended price (None for MARKET)
            filled_price: Actual fill price
            requested_qty: Requested quantity
            filled_qty: Actually filled quantity
            status: Order status (FILLED/PARTIALLY_FILLED/etc)
            placed_at: When order was placed
            filled_at: When order filled
        """
        if not self.enabled:
            return
        
        symbol = symbol.upper()
        
        # Create order record
        record = OrderRecord(
            symbol=symbol,
            order_id=order_id,
            side=side,
            order_type=order_type,
            requested_price=requested_price,
            filled_price=filled_price,
            requested_qty=requested_qty,
            filled_qty=filled_qty,
            status=status,
            placed_at=placed_at or datetime.now(),
            filled_at=filled_at
        )
        
        # Add to history
        self.order_history.append(record)
        
        # Trim history if too large
        if len(self.order_history) > self.max_history:
            self.order_history = self.order_history[-self.max_history:]
        
        # Update metrics
        self._update_metrics(record)
        
        # Log if notable
        self._log_if_notable(record)
    
    def _update_metrics(self, record: OrderRecord) -> None:
        """Update metrics for symbol"""
        symbol = record.symbol
        
        if symbol not in self.symbol_metrics:
            self.symbol_metrics[symbol] = SymbolQualityMetrics(symbol=symbol)
        
        metrics = self.symbol_metrics[symbol]
        metrics.total_orders += 1
        metrics.last_updated = datetime.now()
        
        # Update based on status
        if record.status == "FILLED":
            metrics.filled_orders += 1
        elif record.status == "REJECTED":
            metrics.rejected_orders += 1
        elif record.status == "CANCELED":
            metrics.canceled_orders += 1
        
        # Update slippage if available
        if record.slippage is not None:
            metrics.total_slippage += record.slippage
            metrics.slippage_count += 1
        
        # Update execution time if available
        if record.execution_time_ms is not None:
            metrics.execution_times.append(record.execution_time_ms)
            # Keep only last 100 execution times per symbol
            if len(metrics.execution_times) > 100:
                metrics.execution_times = metrics.execution_times[-100:]
    
    def _log_if_notable(self, record: OrderRecord) -> None:
        """Log if order has notable characteristics"""
        # High slippage
        if record.slippage and abs(record.slippage) > SLIPPAGE_ALERT_THRESHOLD:
            logger.warning(
                f"⚠️ {record.symbol}: High slippage {record.slippage*100:.2f}% | "
                f"Order: {record.order_id} | "
                f"Expected: {record.requested_price} → "
                f"Got: {record.filled_price}"
            )
        
        # Partial fill
        if 0 < record.fill_rate < 0.95:
            logger.warning(
                f"⚠️ {record.symbol}: Partial fill {record.fill_rate*100:.1f}% | "
                f"Order: {record.order_id} | "
                f"Requested: {record.requested_qty} → "
                f"Filled: {record.filled_qty}"
            )
        
        # Rejection
        if record.status == "REJECTED":
            logger.warning(
                f"🚫 {record.symbol}: Order REJECTED | "
                f"Order: {record.order_id} | "
                f"Type: {record.order_type}"
            )
    
    def get_symbol_quality(self, symbol: str) -> Optional[SymbolQualityMetrics]:
        """Get quality metrics for a symbol"""
        symbol = symbol.upper()
        return self.symbol_metrics.get(symbol)
    
    def passes_quality_check(self, symbol: str) -> tuple[bool, str]:
        """
        Check if symbol passes quality thresholds
        
        Returns:
            (passed, reason)
        """
        if not self.enabled:
            return True, "Quality monitoring disabled"
        
        symbol = symbol.upper()
        metrics = self.get_symbol_quality(symbol)
        
        if not metrics:
            # No history = allow (benefit of doubt)
            return True, "No quality history"
        
        # Check minimum orders threshold
        if metrics.total_orders < 5:
            # Not enough data
            return True, "Insufficient data (< 5 orders)"
        
        # Check fill rate
        if metrics.fill_rate < MIN_FILL_RATE:
            return False, f"Low fill rate {metrics.fill_rate*100:.1f}% (min: {MIN_FILL_RATE*100:.0f}%)"
        
        # Check slippage
        if metrics.avg_slippage > MAX_AVG_SLIPPAGE:
            return False, f"High avg slippage {metrics.avg_slippage*100:.2f}% (max: {MAX_AVG_SLIPPAGE*100:.1f}%)"
        
        # All checks passed
        return True, "Quality checks passed"
    
    def get_recent_orders(
        self,
        symbol: Optional[str] = None,
        hours: int = 24,
        limit: int = 100
    ) -> List[OrderRecord]:
        """
        Get recent orders
        
        Args:
            symbol: Filter by symbol (None = all)
            hours: How many hours back to look
            limit: Maximum number of orders
        
        Returns:
            List of order records
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        filtered = [
            order for order in self.order_history
            if order.placed_at >= cutoff
            and (symbol is None or order.symbol.upper() == symbol.upper())
        ]
        
        # Return most recent first
        filtered.reverse()
        return filtered[:limit]
    
    def get_stats(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get quality statistics
        
        Args:
            symbol: Get stats for specific symbol (None = all)
        
        Returns:
            Stats dictionary
        """
        if symbol:
            symbol = symbol.upper()
            metrics = self.get_symbol_quality(symbol)
            if not metrics:
                return {"error": "No data for symbol"}
            
            return {
                "symbol": symbol,
                "total_orders": metrics.total_orders,
                "fill_rate": f"{metrics.fill_rate*100:.1f}%",
                "avg_slippage": f"{metrics.avg_slippage*100:.3f}%",
                "rejection_rate": f"{metrics.rejection_rate*100:.1f}%",
                "avg_execution_ms": f"{metrics.avg_execution_time_ms:.0f}ms",
                "last_updated": metrics.last_updated.strftime("%Y-%m-%d %H:%M:%S")
            }
        
        # Overall stats
        total_orders = sum(m.total_orders for m in self.symbol_metrics.values())
        total_filled = sum(m.filled_orders for m in self.symbol_metrics.values())
        total_rejected = sum(m.rejected_orders for m in self.symbol_metrics.values())
        
        return {
            "enabled": self.enabled,
            "tracked_symbols": len(self.symbol_metrics),
            "total_orders": total_orders,
            "overall_fill_rate": f"{(total_filled/total_orders*100) if total_orders > 0 else 0:.1f}%",
            "overall_rejection_rate": f"{(total_rejected/total_orders*100) if total_orders > 0 else 0:.1f}%",
            "history_size": len(self.order_history),
            "thresholds": {
                "min_fill_rate": f"{MIN_FILL_RATE*100:.0f}%",
                "max_avg_slippage": f"{MAX_AVG_SLIPPAGE*100:.1f}%"
            }
        }
    
    def clear_symbol_history(self, symbol: str) -> None:
        """Clear history for a symbol"""
        symbol = symbol.upper()
        if symbol in self.symbol_metrics:
            del self.symbol_metrics[symbol]
        
        self.order_history = [
            order for order in self.order_history
            if order.symbol != symbol
        ]
        
        logger.info(f"🗑️ {symbol}: Quality history cleared")


# Singleton instance
_quality_monitor: Optional[OrderQualityMonitor] = None


def get_quality_monitor() -> OrderQualityMonitor:
    """Get or create singleton quality monitor"""
    global _quality_monitor
    if _quality_monitor is None:
        _quality_monitor = OrderQualityMonitor()
    return _quality_monitor


# Convenience functions
def record_order(**kwargs) -> None:
    """Record an order execution"""
    monitor = get_quality_monitor()
    monitor.record_order(**kwargs)


def check_symbol_quality(symbol: str) -> tuple[bool, str]:
    """Check if symbol passes quality thresholds"""
    monitor = get_quality_monitor()
    return monitor.passes_quality_check(symbol)


# Public API
__all__ = [
    "OrderQualityMonitor",
    "OrderRecord",
    "SymbolQualityMetrics",
    "get_quality_monitor",
    "record_order",
    "check_symbol_quality"
]
