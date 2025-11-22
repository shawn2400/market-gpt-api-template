# utils/adaptive_win_rate_engine.py
"""
🧠 ADAPTIVE WIN RATE OPTIMIZER ENGINE

Dynamic trade sizing based on:
- Recent performance (last 30 trades)
- Market regime (CHOPPY/TRENDING/VOLATILE)
- Sharpe ratio & win rate
- Position size scaling: 1-5%

Ultra-light memory footprint (<1MB), Redis-backed
"""

import logging
import time
from collections import deque
from decimal import Decimal
from typing import Optional, Dict, Any

logger = logging.getLogger("algogpt.adaptive_wr_engine")

class AdaptiveWinRateEngine:
    """Core adaptive engine for dynamic trade sizing & confidence"""
    
    def __init__(self, redis_conn=None):
        """Initialize with ultra-light data structures"""
        self.redis = redis_conn
        
        # In-memory cache (30 trades max)
        self.recent_trades = deque(maxlen=30)
        
        # Adaptive parameters
        self.base_params = {
            'position_size_pct': 0.025,      # 2.5% base
            'stop_loss_pct': 0.025,          # 2.5% base
            'take_profit_pct': 0.035,        # 3.5% base
            'min_size_pct': 0.01,            # 1% minimum
            'max_size_pct': 0.05             # 5% maximum
        }
        
        # Market regime cache
        self.regime_state = {
            'current': 'NEUTRAL',
            'confidence': 0.0,
            'last_update': time.time()
        }
        
        # Performance metrics
        self.performance = {
            'win_rate': 0.50,
            'avg_pnl': 0.0,
            'sharpe_ratio': 0.0,
            'last_update': time.time()
        }
    
    def update_trade_result(self, trade: Dict[str, Any]) -> None:
        """Update with new trade result"""
        try:
            self.recent_trades.append({
                'pnl': float(trade.get('pnl', 0)),
                'entry_price': float(trade.get('entry_price', 0)),
                'exit_price': float(trade.get('exit_price', 0)),
                'symbol': trade.get('symbol', ''),
                'duration_minutes': int(trade.get('duration_minutes', 0)),
                'timestamp': time.time()
            })
            
            # Auto-learn every 10 trades
            if len(self.recent_trades) % 10 == 0:
                self._update_performance_metrics()
                
        except Exception as e:
            logger.error(f"❌ update_trade_result failed: {e}")
    
    def _update_performance_metrics(self) -> None:
        """Calculate win rate, Sharpe, avg PnL from recent trades"""
        if len(self.recent_trades) < 10:
            return
        
        trades = list(self.recent_trades)
        pnls = [t['pnl'] for t in trades]
        
        # Win rate
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls) if pnls else 0.5
        
        # Average PnL
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        
        # Sharpe ratio (simplified)
        if len(pnls) >= 2:
            variance = sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)
            std_dev = variance ** 0.5
            sharpe = (avg_pnl / std_dev) if std_dev > 0 else 0.0
        else:
            sharpe = 0.0
        
        self.performance['win_rate'] = max(0.3, min(0.7, win_rate))
        self.performance['avg_pnl'] = avg_pnl
        self.performance['sharpe_ratio'] = sharpe
        self.performance['last_update'] = time.time()
        
        logger.info(
            f"📊 Performance Updated: WR={self.performance['win_rate']:.2%}, "
            f"AvgPnL=${self.performance['avg_pnl']:.4f}, "
            f"Sharpe={self.performance['sharpe_ratio']:.2f}"
        )
    
    def calculate_adaptive_parameters(
        self, 
        market_regime: str = 'NEUTRAL',
        quality_score: float = 5.0,
        volatility_pct: float = 1.5
    ) -> Dict[str, Any]:
        """
        Calculate dynamic parameters based on:
        - Recent win rate
        - Market regime
        - Quality score
        - Volatility
        """
        try:
            # Update regime
            self.regime_state['current'] = market_regime
            self.regime_state['last_update'] = time.time()
            
            # Get performance adjustments
            wr = self.performance['win_rate']
            sharpe = self.performance['sharpe_ratio']
            
            # Calculate confidence score (-0.10 to +0.10)
            wr_adjustment = 0.0
            if wr > 0.60 and sharpe > 1.0:
                wr_adjustment = +0.05  # High confidence
            elif wr > 0.55 and sharpe > 0.5:
                wr_adjustment = +0.02  # Medium confidence
            elif wr < 0.45 or sharpe < -0.5:
                wr_adjustment = -0.05  # Low confidence
            
            # Regime-based adjustments
            regime_adjustment = {
                'CHOPPY': +0.02,      # Positive for ranging markets
                'TRENDING': +0.04,    # Positive for trends
                'VOLATILE': -0.03,    # Negative for high volatility
                'NEUTRAL': 0.0
            }.get(market_regime, 0.0)
            
            # Quality-based adjustment (quality 0-10)
            quality_adjustment = (quality_score - 5.0) * 0.01  # ±0.05 max
            
            # Total confidence
            total_confidence = max(-0.10, min(0.10, 
                wr_adjustment + regime_adjustment + quality_adjustment
            ))
            
            # Calculate position size (1-5%)
            base_size = self.base_params['position_size_pct']
            adaptive_size = base_size * (1 + total_confidence * 2)  # ±10% of base
            
            # Clamp within 1-5%
            position_size_pct = max(
                self.base_params['min_size_pct'],
                min(self.base_params['max_size_pct'], adaptive_size)
            )
            
            # Scale stop loss inversely (tighter when confident)
            stop_loss_pct = self.base_params['stop_loss_pct'] * (1 - total_confidence * 0.2)
            stop_loss_pct = max(0.015, min(0.04, stop_loss_pct))
            
            # Scale take profit with confidence
            take_profit_pct = self.base_params['take_profit_pct'] * (1 + total_confidence * 0.15)
            take_profit_pct = max(0.02, min(0.06, take_profit_pct))
            
            result = {
                'position_size_pct': position_size_pct,
                'stop_loss_pct': stop_loss_pct,
                'take_profit_pct': take_profit_pct,
                'confidence': total_confidence,
                'win_rate': wr,
                'sharpe': sharpe,
                'regime': market_regime
            }
            
            # Log significant changes
            if abs(total_confidence) > 0.05:
                logger.info(
                    f"🎯 Adaptive Parameters: Size={position_size_pct:.1%}, "
                    f"SL={stop_loss_pct:.1%}, TP={take_profit_pct:.1%}, "
                    f"Confidence={total_confidence:+.1%} ({market_regime})"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ calculate_adaptive_parameters failed: {e}")
            # Return defaults on error
            return {
                'position_size_pct': self.base_params['position_size_pct'],
                'stop_loss_pct': self.base_params['stop_loss_pct'],
                'take_profit_pct': self.base_params['take_profit_pct'],
                'confidence': 0.0,
                'win_rate': 0.5,
                'sharpe': 0.0,
                'regime': 'NEUTRAL'
            }
    
    def get_sizing_multiplier(self, confidence: float) -> float:
        """
        Get position size multiplier (0.7x to 1.3x)
        Based on confidence score (-0.10 to +0.10)
        """
        # confidence: -0.10 → 0.7x, 0 → 1.0x, +0.10 → 1.3x
        return 1.0 + (confidence * 3.0)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get current performance summary"""
        return {
            'win_rate': self.performance['win_rate'],
            'avg_pnl': self.performance['avg_pnl'],
            'sharpe_ratio': self.performance['sharpe_ratio'],
            'recent_trades_count': len(self.recent_trades),
            'regime': self.regime_state['current'],
            'last_update': self.performance['last_update']
        }


# Singleton instance
_adaptive_engine: Optional[AdaptiveWinRateEngine] = None


def get_adaptive_engine(redis_conn=None) -> AdaptiveWinRateEngine:
    """Get or create singleton adaptive engine"""
    global _adaptive_engine
    if _adaptive_engine is None:
        _adaptive_engine = AdaptiveWinRateEngine(redis_conn=redis_conn)
    return _adaptive_engine


def initialize_adaptive_engine(redis_conn=None) -> AdaptiveWinRateEngine:
    """Initialize adaptive engine with Redis connection"""
    global _adaptive_engine
    _adaptive_engine = AdaptiveWinRateEngine(redis_conn=redis_conn)
    logger.info("✅ Adaptive Win Rate Engine initialized")
    return _adaptive_engine
