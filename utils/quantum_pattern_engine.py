#!/usr/bin/env python3
"""
Quantum Pattern Recognition Engine
==================================
Learns from recent successful trades, predicts next profitable patterns.
Simple, fast, practical - NOT theoretical.

Features:
- Track last 50 trades (wins/losses)
- Pattern recognition (price action, timeframe combinations)
- Confidence boost for patterns that worked recently
- Real-time learning & adaptation
"""

import logging
import json
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime, timezone, timedelta
from collections import defaultdict

logger = logging.getLogger("quantum_pattern_engine")


class QuantumPatternEngine:
    """
    Learn from recent trades, predict winning patterns.
    """
    
    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.trade_history: List[Dict[str, Any]] = []
        self.pattern_cache: Dict[str, Any] = defaultdict(lambda: {
            "wins": 0, "losses": 0, "win_rate": 0.0, "last_seen": None
        })
        self.market_regimes = defaultdict(lambda: {
            "trending_patterns": [], "choppy_patterns": [], "volatile_patterns": []
        })
        
        logger.info("🧠 Quantum Pattern Engine initialized (learning mode)")
    
    def add_trade(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quality_score: float,
        market_regime: str,
        atr_pct: float,
        adx: Optional[float],
        result: str  # "win" or "loss"
    ) -> None:
        """
        Log completed trade for pattern learning.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            entry_price: Entry price
            exit_price: Exit price
            quality_score: AI quality score
            market_regime: TRENDING/CHOPPY/VOLATILE
            atr_pct: ATR as percentage
            adx: ADX value if available
            result: "win" or "loss"
        """
        try:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            
            trade_record = {
                "symbol": symbol,
                "entry": entry_price,
                "exit": exit_price,
                "pnl_pct": pnl_pct,
                "quality": quality_score,
                "regime": market_regime,
                "atr": atr_pct,
                "adx": adx,
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            self.trade_history.append(trade_record)
            
            # Keep only recent history
            if len(self.trade_history) > self.max_history:
                self.trade_history = self.trade_history[-self.max_history:]
            
            # Extract pattern
            pattern_key = self._extract_pattern(
                symbol=symbol,
                quality=quality_score,
                regime=market_regime,
                atr=atr_pct,
                adx=adx
            )
            
            # Update pattern statistics
            if result == "win":
                self.pattern_cache[pattern_key]["wins"] += 1
            else:
                self.pattern_cache[pattern_key]["losses"] += 1
            
            # Recalculate win rate
            total = self.pattern_cache[pattern_key]["wins"] + self.pattern_cache[pattern_key]["losses"]
            if total > 0:
                self.pattern_cache[pattern_key]["win_rate"] = (
                    self.pattern_cache[pattern_key]["wins"] / total
                )
            
            self.pattern_cache[pattern_key]["last_seen"] = datetime.now(timezone.utc).isoformat()
            
            logger.debug(
                f"📊 Trade logged: {symbol} {result.upper()} | "
                f"Pattern: {pattern_key} | Win rate: {self.pattern_cache[pattern_key]['win_rate']:.1%}"
            )
            
        except Exception as e:
            logger.warning(f"Failed to log trade: {e}")
    
    def get_pattern_confidence_boost(
        self,
        symbol: str,
        quality_score: float,
        market_regime: str,
        atr_pct: float,
        adx: Optional[float]
    ) -> Tuple[float, str]:
        """
        Check if current trade matches a successful pattern.
        
        Returns:
            (confidence_boost: 0.0-1.0, reason: str)
        """
        pattern_key = self._extract_pattern(
            symbol=symbol,
            quality=quality_score,
            regime=market_regime,
            atr=atr_pct,
            adx=adx
        )
        
        if pattern_key not in self.pattern_cache:
            return 0.0, "New pattern (no history)"
        
        pattern_stats = self.pattern_cache[pattern_key]
        
        # Only boost if pattern has proven history
        total_trades = pattern_stats["wins"] + pattern_stats["losses"]
        
        if total_trades < 3:
            return 0.0, f"Pattern too new ({total_trades} trades)"
        
        win_rate = pattern_stats["win_rate"]
        
        # Confidence boost formula:
        # If win_rate > 60%: boost = (win_rate - 0.5) * 0.8
        # Max boost: 0.5 (50% confidence increase)
        
        if win_rate > 0.60:
            boost = min((win_rate - 0.5) * 0.8, 0.5)
            reason = f"Pattern proven: {win_rate:.1%} win rate ({total_trades} trades)"
            return boost, reason
        elif win_rate > 0.50:
            boost = 0.15
            reason = f"Pattern promising: {win_rate:.1%} win rate ({total_trades} trades)"
            return boost, reason
        else:
            return -0.2, f"Pattern struggling: {win_rate:.1%} win rate - AVOID"
    
    def _extract_pattern(
        self,
        symbol: str,
        quality: float,
        regime: str,
        atr: float,
        adx: Optional[float]
    ) -> str:
        """
        Convert trade parameters into pattern key.
        
        Example: "BTCUSDT_Q8.5_TRENDING_ATR2.1_ADX35" → hashable pattern
        """
        # Quantize parameters for pattern matching
        quality_bucket = f"Q{int(quality * 2) / 2:.1f}"  # Q5.5, Q6.0, Q6.5, etc.
        atr_bucket = f"ATR{int(atr * 10) / 10:.1f}"      # ATR1.0, ATR1.1, etc.
        adx_bucket = f"ADX{int(adx / 10) * 10}" if adx else "ADXnone"
        
        pattern = f"{symbol}_{quality_bucket}_{regime}_{atr_bucket}_{adx_bucket}"
        return pattern
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """
        Get engine learning statistics.
        """
        total_trades = len(self.trade_history)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "patterns_learned": 0,
                "status": "No trades yet"
            }
        
        wins = sum(1 for t in self.trade_history if t["result"] == "win")
        losses = total_trades - wins
        
        winning_patterns = {
            k: v for k, v in self.pattern_cache.items()
            if v["win_rate"] > 0.60
        }
        
        return {
            "total_trades": total_trades,
            "overall_win_rate": f"{wins / total_trades:.1%}",
            "patterns_learned": len(self.pattern_cache),
            "high_confidence_patterns": len(winning_patterns),
            "recent_pattern_perf": {
                k: {
                    "win_rate": f"{v['win_rate']:.1%}",
                    "total": v["wins"] + v["losses"]
                }
                for k, v in list(self.pattern_cache.items())[-10:]
            }
        }


# Global instance
_quantum_pattern_engine: Optional[QuantumPatternEngine] = None


def get_quantum_pattern_engine() -> QuantumPatternEngine:
    """Get or create global pattern engine."""
    global _quantum_pattern_engine
    if _quantum_pattern_engine is None:
        _quantum_pattern_engine = QuantumPatternEngine()
    return _quantum_pattern_engine
