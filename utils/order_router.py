#!/usr/bin/env python3
# utils/order_router.py
"""
Smart LIMIT+MARKET Order Router
================================

Dynamically selects optimal order type based on:
- Market volatility (ATR%)
- Spread tightness
- Signal urgency
- Book depth
- Order purpose (entry/exit/TP/SL)

Decision Matrix:
- LIMIT: Low volatility, tight spreads, sniper precision
- MARKET: High volatility, urgent execution, breakouts
- HYBRID: Medium volatility, large positions, iceberg style
"""

import os
import logging
from typing import Dict, Any, Optional, Literal
from datetime import datetime, timezone

logger = logging.getLogger("algogpt.order_router")

# Configuration
ATR_LOW_THRESHOLD = float(os.getenv("ORDER_ROUTER_ATR_LOW", "0.015"))  # 1.5%
ATR_HIGH_THRESHOLD = float(os.getenv("ORDER_ROUTER_ATR_HIGH", "0.03"))  # 3%
SPREAD_TIGHT_THRESHOLD = float(os.getenv("ORDER_ROUTER_SPREAD_TIGHT", "0.0005"))  # 0.05%
SIGNAL_AGE_STALE_SEC = int(os.getenv("ORDER_ROUTER_SIGNAL_AGE", "30"))

OrderType = Literal["LIMIT", "MARKET", "HYBRID"]
OrderPurpose = Literal["ENTRY", "EXIT", "TP", "SL", "GRID"]


class SmartOrderRouter:
    """
    Intelligent order type selector based on market conditions
    
    Usage:
        router = SmartOrderRouter()
        decision = router.route_order(
            atr_pct=0.025,
            spread_pct=0.0003,
            signal_age_sec=15,
            purpose="ENTRY",
            urgency="normal"
        )
        # decision = {"order_type": "LIMIT", "reason": "...", "params": {...}}
    """
    
    def __init__(self):
        self.atr_low = ATR_LOW_THRESHOLD
        self.atr_high = ATR_HIGH_THRESHOLD
        self.spread_tight = SPREAD_TIGHT_THRESHOLD
        self.signal_stale = SIGNAL_AGE_STALE_SEC
        
        logger.info(
            f"📍 Smart Order Router initialized | "
            f"ATR Low: {self.atr_low*100:.1f}% | "
            f"ATR High: {self.atr_high*100:.1f}% | "
            f"Spread Tight: {self.spread_tight*100:.2f}%"
        )
    
    def route_order(
        self,
        *,
        atr_pct: float,
        spread_pct: Optional[float] = None,
        signal_age_sec: Optional[int] = None,
        purpose: OrderPurpose = "ENTRY",
        urgency: Literal["low", "normal", "high", "critical"] = "normal",
        book_depth_ok: bool = True,
        is_breakout: bool = False,
        position_size_large: bool = False
    ) -> Dict[str, Any]:
        """
        Route order to optimal type based on market conditions
        
        Args:
            atr_pct: ATR as percentage of price (e.g., 0.025 = 2.5%)
            spread_pct: Bid-ask spread as percentage (e.g., 0.0003 = 0.03%)
            signal_age_sec: Age of trading signal in seconds
            purpose: Order purpose (ENTRY/EXIT/TP/SL/GRID)
            urgency: Urgency level (low/normal/high/critical)
            book_depth_ok: Whether order book has sufficient depth
            is_breakout: Whether this is a breakout trade
            position_size_large: Whether position size requires splitting
            
        Returns:
            {
                "order_type": "LIMIT" | "MARKET" | "HYBRID",
                "reason": "explanation of decision",
                "params": {"post_only": bool, "time_in_force": str, ...},
                "score": int (confidence 1-10)
            }
        """
        # Default spread if not provided
        if spread_pct is None:
            spread_pct = 0.001  # Assume 0.1% if unknown
        
        # Default signal age
        if signal_age_sec is None:
            signal_age_sec = 0
        
        # Calculate decision scores
        scores = self._calculate_scores(
            atr_pct=atr_pct,
            spread_pct=spread_pct,
            signal_age_sec=signal_age_sec,
            purpose=purpose,
            urgency=urgency,
            book_depth_ok=book_depth_ok,
            is_breakout=is_breakout,
            position_size_large=position_size_large
        )
        
        # Make decision
        decision = self._make_decision(scores, purpose)
        
        logger.info(
            f"📍 Order Router: {decision['order_type']} | "
            f"Purpose: {purpose} | ATR: {atr_pct*100:.1f}% | "
            f"Reason: {decision['reason']}"
        )
        
        return decision
    
    def _calculate_scores(
        self,
        atr_pct: float,
        spread_pct: float,
        signal_age_sec: int,
        purpose: OrderPurpose,
        urgency: str,
        book_depth_ok: bool,
        is_breakout: bool,
        position_size_large: bool
    ) -> Dict[str, int]:
        """
        Calculate scores for each order type (1-10 scale)
        Higher score = better fit
        """
        limit_score = 0
        market_score = 0
        
        # 1. VOLATILITY SCORING (most important)
        if atr_pct < self.atr_low:  # Low volatility
            limit_score += 5
            market_score += 1
        elif atr_pct > self.atr_high:  # High volatility
            limit_score += 1
            market_score += 5
        else:  # Medium volatility
            limit_score += 3
            market_score += 3
        
        # 2. SPREAD SCORING
        if spread_pct < self.spread_tight:  # Tight spread
            limit_score += 3
            market_score += 1
        else:  # Wide spread
            limit_score += 1
            market_score += 2
        
        # 3. SIGNAL AGE SCORING
        if signal_age_sec > self.signal_stale:  # Stale signal
            limit_score += 1
            market_score += 4
        else:  # Fresh signal
            limit_score += 2
            market_score += 1
        
        # 4. URGENCY SCORING
        urgency_weights = {
            "low": (3, 0),
            "normal": (2, 1),
            "high": (1, 3),
            "critical": (0, 5)
        }
        l_add, m_add = urgency_weights.get(urgency, (2, 1))
        limit_score += l_add
        market_score += m_add
        
        # 5. PURPOSE SCORING
        if purpose in ("TP", "GRID"):  # Precision matters
            limit_score += 4
            market_score += 0
        elif purpose in ("SL", "EXIT"):  # Speed matters
            limit_score += 0
            market_score += 4
        else:  # ENTRY - balanced
            limit_score += 2
            market_score += 2
        
        # 6. BREAKOUT SCORING
        if is_breakout:
            limit_score += 0
            market_score += 5
        
        # 7. BOOK DEPTH SCORING
        if not book_depth_ok:
            limit_score += 0
            market_score += 3
        else:
            limit_score += 2
            market_score += 0
        
        # 8. POSITION SIZE SCORING
        if position_size_large:
            # Hybrid preferred for large positions
            limit_score += 1
            market_score += 1
        
        return {
            "limit": min(limit_score, 10),
            "market": min(market_score, 10)
        }
    
    def _make_decision(
        self, 
        scores: Dict[str, int], 
        purpose: OrderPurpose
    ) -> Dict[str, Any]:
        """
        Make final order type decision based on scores
        """
        limit_score = scores["limit"]
        market_score = scores["market"]
        
        # Decision logic
        if market_score >= 8:  # Strong MARKET preference
            return {
                "order_type": "MARKET",
                "reason": f"High urgency/volatility (score: {market_score}/10)",
                "params": {},
                "score": market_score
            }
        
        elif limit_score >= 7:  # Strong LIMIT preference
            params = {
                "post_only": purpose in ("GRID", "TP"),  # Post-only for GRID/TP
                "time_in_force": "GTC"
            }
            return {
                "order_type": "LIMIT",
                "reason": f"Low volatility, sniper precision (score: {limit_score}/10)",
                "params": params,
                "score": limit_score
            }
        
        elif abs(limit_score - market_score) <= 2:  # Close scores
            # Hybrid approach: start with LIMIT, escalate to MARKET if needed
            return {
                "order_type": "HYBRID",
                "reason": f"Medium conditions (LIMIT: {limit_score}, MARKET: {market_score})",
                "params": {
                    "start_with": "LIMIT",
                    "escalate_after_sec": 60,
                    "fallback_to": "MARKET"
                },
                "score": max(limit_score, market_score)
            }
        
        elif limit_score > market_score:
            params = {
                "post_only": purpose in ("GRID", "TP"),
                "time_in_force": "GTC"
            }
            return {
                "order_type": "LIMIT",
                "reason": f"Limit preferred (score: {limit_score} vs {market_score})",
                "params": params,
                "score": limit_score
            }
        
        else:
            return {
                "order_type": "MARKET",
                "reason": f"Market preferred (score: {market_score} vs {limit_score})",
                "params": {},
                "score": market_score
            }
    
    def get_router_stats(self) -> Dict[str, Any]:
        """Get router configuration summary"""
        return {
            "atr_thresholds": {
                "low": f"{self.atr_low*100:.1f}%",
                "high": f"{self.atr_high*100:.1f}%"
            },
            "spread_threshold": f"{self.spread_tight*100:.2f}%",
            "signal_stale_sec": self.signal_stale,
            "supported_types": ["LIMIT", "MARKET", "HYBRID"]
        }


# Singleton instance
_router: Optional[SmartOrderRouter] = None


def get_order_router() -> SmartOrderRouter:
    """Get or create singleton router instance"""
    global _router
    if _router is None:
        _router = SmartOrderRouter()
    return _router


# Convenience function
def route_smart_order(
    atr_pct: float,
    purpose: OrderPurpose = "ENTRY",
    **kwargs
) -> Dict[str, Any]:
    """
    Quick routing function
    
    Example:
        decision = route_smart_order(
            atr_pct=0.025,
            purpose="GRID",
            urgency="low"
        )
    """
    router = get_order_router()
    return router.route_order(atr_pct=atr_pct, purpose=purpose, **kwargs)
