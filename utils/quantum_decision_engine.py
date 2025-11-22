"""
🎯 QUANTUM DECISION ENGINE - Intelligent Trade Qualification & Routing
Smart filters and decision routing for optimal trade execution
"""

import logging
from typing import Dict, List, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)

class TradeStrategy(Enum):
    """Available trading strategies"""
    WAIT = "WAIT"
    GRID = "GRID"
    TREND = "TREND"
    SCALP = "SCALP"
    HEDGE = "HEDGE"

class TradeQualificationSystem:
    """Multi-level trade qualification system"""
    
    def __init__(self):
        self.min_confidence = 0.75  # 75% minimum confidence
        self.min_rr_ratio = 1.5    # 1:1.5 minimum risk/reward
        self.volume_spike_threshold = 1.5  # 150% of avg
        
    def qualify_trade(self, signal: Dict[str, Any]) -> float:
        """
        Qualify trade signal (0.0-1.0 score)
        Only trades scoring >= 0.75 proceed to council
        """
        
        score = 0.0
        
        # 1. Technical Analysis Score (30%)
        tech_score = signal.get('technical_score', 0) / 10.0
        if tech_score > 0.7:
            score += 0.3
        else:
            score += tech_score * 0.3
        
        # 2. Fundamental Analysis Score (20%)
        fund_score = signal.get('fundamental_score', 0) / 10.0
        if fund_score > 0.6:
            score += 0.2
        else:
            score += fund_score * 0.2
        
        # 3. Volume Confirmation (20%)
        if signal.get('volume_confirmed', False):
            volume = signal.get('volume', 0)
            avg_volume = signal.get('avg_volume', 1)
            if volume > avg_volume * self.volume_spike_threshold:
                score += 0.2
            else:
                score += 0.1
        
        # 4. Trend Alignment (15%)
        if signal.get('trend_aligned', False):
            score += 0.15
        
        # 5. Risk/Reward Ratio (15%)
        rr_ratio = signal.get('risk_reward_ratio', 1.0)
        if rr_ratio >= self.min_rr_ratio:
            score += 0.15
        elif rr_ratio >= 1.2:
            score += 0.1
        
        return min(score, 1.0)
    
    def is_qualified(self, signal: Dict[str, Any]) -> bool:
        """Check if signal is qualified for trading"""
        score = self.qualify_trade(signal)
        return score >= 0.75
    
    def get_qualification_reason(self, signal: Dict[str, Any]) -> str:
        """Get explanation for qualification decision"""
        
        score = self.qualify_trade(signal)
        
        if score >= 0.75:
            return f"✅ QUALIFIED (score: {score:.2f})"
        elif score >= 0.5:
            return f"⚠️ MARGINAL (score: {score:.2f} - needs improvement)"
        else:
            return f"❌ NOT QUALIFIED (score: {score:.2f})"


class QuantumDecisionRouter:
    """Routes qualified trades to appropriate strategies"""
    
    def __init__(self):
        self.qualification_system = TradeQualificationSystem()
    
    def determine_strategy(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determine best strategy for signal:
        - WAIT: Holding or waiting for confirmation
        - GRID: Grid trading mode
        - TREND: Trend following
        - SCALP: Quick scalping opportunities
        - HEDGE: Hedging existing positions
        """
        
        # First check qualification
        qual_score = self.qualification_system.qualify_trade(signal)
        
        if qual_score < 0.5:
            return {
                'strategy': TradeStrategy.WAIT.value,
                'reason': 'Signal not qualified enough',
                'qualification_score': qual_score,
                'confidence': 0.3
            }
        
        # Determine best strategy based on signal characteristics
        symbol = signal.get('symbol', 'UNKNOWN')
        quality_score = signal.get('quality_score', 0)
        volatility = signal.get('volatility', 0)
        trend = signal.get('trend', 'CHOPPY')
        
        logger.info(f"🎯 ROUTING {symbol}: quality={quality_score:.1f}, vol={volatility:.1f}, trend={trend}")
        
        # Strategy selection logic
        if quality_score >= 8.5 and trend in ['BULLISH', 'BEARISH']:
            strategy = TradeStrategy.TREND.value
            reason = "High quality trend signal"
            confidence = 0.85
        
        elif quality_score >= 7.5 and volatility > 1.5:
            strategy = TradeStrategy.GRID.value
            reason = "Grid trading - high volatility conditions"
            confidence = 0.75
        
        elif quality_score >= 7.0 and volatility > 2.0:
            strategy = TradeStrategy.SCALP.value
            reason = "Scalping - extreme volatility"
            confidence = 0.70
        
        elif trend == 'CHOPPY' and quality_score >= 6.0:
            strategy = TradeStrategy.GRID.value
            reason = "Choppy market - grid strategy optimal"
            confidence = 0.65
        
        else:
            strategy = TradeStrategy.WAIT.value
            reason = f"Waiting for better conditions (quality={quality_score:.1f})"
            confidence = 0.4
        
        return {
            'strategy': strategy,
            'reason': reason,
            'qualification_score': qual_score,
            'confidence': confidence,
            'recommended_leverage': self._calc_leverage(quality_score, volatility),
            'recommended_position_size': self._calc_position_size(qual_score, quality_score)
        }
    
    def _calc_leverage(self, quality: float, volatility: float) -> int:
        """Calculate recommended leverage (3-35x)"""
        
        # Higher quality + lower volatility = higher leverage
        base_leverage = int(3 + (quality / 10.0) * 20)
        volatility_reduction = int(volatility * 5)
        
        leverage = max(3, min(35, base_leverage - volatility_reduction))
        
        return leverage
    
    def _calc_position_size(self, qual_score: float, quality: float) -> float:
        """Calculate recommended position size (%)"""
        
        # 2-4% based on qualification
        base_size = 2.0 + (qual_score * 2.0)
        
        return min(4.0, base_size)


class QuantumDecisionEngine:
    """Main decision engine combining all systems"""
    
    def __init__(self):
        self.router = QuantumDecisionRouter()
        self.decision_log = []
    
    def process_trade_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full signal processing pipeline:
        1. Qualification check
        2. Strategy routing
        3. Parameter calculation
        """
        
        symbol = signal.get('symbol', 'UNKNOWN')
        logger.info(f"🔍 PROCESSING SIGNAL: {symbol}")
        
        # Step 1: Qualification
        qual_system = TradeQualificationSystem()
        qual_score = qual_system.qualify_trade(signal)
        is_qualified = qual_score >= 0.75
        
        logger.info(f"   📊 Qualification: {qual_system.get_qualification_reason(signal)}")
        
        if not is_qualified:
            return {
                'symbol': symbol,
                'action': 'REJECT',
                'qualification_score': qual_score,
                'reason': 'Failed qualification check'
            }
        
        # Step 2: Strategy routing
        strategy_decision = self.router.determine_strategy(signal)
        
        logger.info(f"   🎯 Strategy: {strategy_decision['strategy']} ({strategy_decision['confidence']:.1%} confidence)")
        
        # Step 3: Build full decision
        decision = {
            'symbol': symbol,
            'action': 'ROUTE_TO_COUNCIL' if strategy_decision['strategy'] != 'WAIT' else 'WAIT',
            'qualification_score': qual_score,
            'strategy': strategy_decision['strategy'],
            'strategy_reason': strategy_decision['reason'],
            'confidence': strategy_decision['confidence'],
            'leverage': strategy_decision['recommended_leverage'],
            'position_size': strategy_decision['recommended_position_size'],
            'timestamp': __import__('datetime').datetime.now().isoformat()
        }
        
        self.decision_log.append(decision)
        
        return decision


# Singleton instances
_decision_engine = None

def get_decision_engine() -> QuantumDecisionEngine:
    """Get or create decision engine singleton"""
    global _decision_engine
    if _decision_engine is None:
        _decision_engine = QuantumDecisionEngine()
        logger.info("✅ Quantum Decision Engine initialized")
    return _decision_engine
