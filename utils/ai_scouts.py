#!/usr/bin/env python3
"""
AI Scouts System - Market Scanner + Technical Analyst
=======================================================
2 specialized AI agents that analyze markets and propose strategies.

Scouts:
1. Market Scanner - Scans 534 symbols, identifies opportunities
2. Technical Analyst - Deep technical analysis, scores setups

MetaBrain v9.0:
- Uses Regime Detector to identify market conditions
- Uses Dynamic Protection Manager for regime-specific parameters
- Proposes BOTH strategy (LONG/SHORT/GRID) AND order type (LIMIT/MARKET)

Both provide detailed reasoning for their recommendations.
"""

import logging
from typing import Dict, Any, Optional, List, Literal
from decimal import Decimal

from utils.metabrain.regime_detector import regime_detector, MarketRegime
from utils.metabrain.dynamic_protection_manager import protection_manager

logger = logging.getLogger("algogpt.ai_scouts")


class MarketScanner:
    """
    Market Scanner Scout - Identifies trading opportunities across all markets.
    
    Responsibilities:
    - Scan 534 Binance Futures symbols
    - Identify volume surges, breakouts, reversals
    - Detect market regime using Regime Detector
    - Propose strategy (LONG/SHORT/GRID) + order type (LIMIT/MARKET)
    - Score opportunity (0-10) with regime-specific criteria
    """
    
    def __init__(self):
        self.logger = logging.getLogger("algogpt.market_scanner")
        self.logger.info("Market Scanner Scout initialized - 534 symbols monitored with Regime Detection")
    
    def scan_symbol(self, symbol: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scan a single symbol for trading opportunities.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            market_data: Dict with price, volume, indicators
        
        Returns:
            Dict with score, strategy, reasoning
        """
        try:
            score = 0.0
            reasons = []
            strategy = "NONE"
            
            volume_24h = market_data.get("volume_24h", 0)
            volume_avg = market_data.get("volume_avg_7d", volume_24h)
            volume_surge = (volume_24h / volume_avg - 1) * 100 if volume_avg > 0 else 0
            
            if volume_surge > 50:
                score += 1.5
                reasons.append(f"נפח עצום +{volume_surge:.0f}%")
            elif volume_surge > 30:
                score += 1.0
                reasons.append(f"נפח חזק +{volume_surge:.0f}%")
            elif volume_surge < -30:
                score -= 0.5
                reasons.append(f"נפח חלש {volume_surge:.0f}%")
            
            liquidity = market_data.get("liquidity_score", 5.0)
            if liquidity >= 8.0:
                score += 1.0
                reasons.append("נזילות מצוינת")
            elif liquidity < 5.0:
                score -= 1.0
                reasons.append("נזילות נמוכה")
            
            price_change_24h = market_data.get("price_change_24h_pct", 0)
            if abs(price_change_24h) > 5:
                score += 0.5
                reasons.append(f"תנועה חזקה {price_change_24h:+.1f}%")
                strategy = "LONG" if price_change_24h > 0 else "SHORT"
            
            atr_pct = market_data.get("atr_pct", 2.0)
            if atr_pct > 4.0:
                score += 0.5
                reasons.append(f"תנודתיות גבוהה {atr_pct:.1f}%")
            
            rsi = market_data.get("rsi", 50)
            if rsi > 70:
                score += 0.5
                reasons.append(f"RSI אובר-בוט {rsi:.0f}")
                if strategy == "NONE":
                    strategy = "SHORT"
            elif rsi < 30:
                score += 0.5
                reasons.append(f"RSI אובר-סולד {rsi:.0f}")
                if strategy == "NONE":
                    strategy = "LONG"
            
            macd_signal = market_data.get("macd_signal", "neutral")
            if macd_signal == "bullish":
                score += 0.8
                reasons.append("MACD חתך חיובי")
                if strategy == "NONE":
                    strategy = "LONG"
            elif macd_signal == "bearish":
                score += 0.8
                reasons.append("MACD חתך שלילי")
                if strategy == "NONE":
                    strategy = "SHORT"
            
            score = max(0, min(10, score))
            
            regime_indicators = {
                "adx": market_data.get("adx", 0),
                "atr": market_data.get("atr", 0),
                "bb_width": market_data.get("bb_width", 0),
                "price_range_pct": abs(price_change_24h)
            }
            regime = regime_detector.detect_regime(regime_indicators)
            
            order_type = self._suggest_order_type(regime, atr_pct, strategy)
            
            reasoning = " | ".join(reasons) if reasons else "אין אינדיקציה ברורה"
            regime_desc = regime_detector.get_regime_description(regime)
            
            self.logger.debug(
                f"{symbol}: Market Scanner score={score:.1f}, "
                f"strategy={strategy}, regime={regime}, order_type={order_type}, reasons={len(reasons)}"
            )
            
            return {
                "scout": "Market Scanner",
                "symbol": symbol,
                "score": round(score, 1),
                "strategy": strategy,
                "order_type": order_type,
                "market_regime": regime,
                "regime_description": regime_desc,
                "reasoning": reasoning,
                "confidence": "HIGH" if score >= 7.0 else "MEDIUM" if score >= 5.5 else "LOW"
            }
        
        except Exception as e:
            self.logger.error(f"Failed to scan {symbol}: {e}", exc_info=True)
            return {
                "scout": "Market Scanner",
                "symbol": symbol,
                "score": 0,
                "strategy": "NONE",
                "order_type": "LIMIT",
                "market_regime": "CHOPPY",
                "regime_description": "Unknown",
                "reasoning": f"שגיאה: {e}",
                "confidence": "LOW"
            }
    
    def _suggest_order_type(self, regime: str, volatility: float, strategy: str) -> str:
        """
        Suggest order type (LIMIT/MARKET) based on regime and volatility
        
        TRENDING: Prefer MARKET for fast execution
        CHOPPY: Prefer LIMIT for better entry
        VOLATILE: Mix based on urgency
        SIDEWAYS: Prefer LIMIT for precision
        """
        if regime == "TRENDING":
            return "MARKET" if volatility > 3.0 else "LIMIT"
        elif regime == "CHOPPY":
            return "LIMIT"
        elif regime == "VOLATILE":
            return "MARKET" if volatility > 5.0 else "LIMIT"
        else:
            return "LIMIT"


class TechnicalAnalyst:
    """
    Technical Analyst Scout - Deep technical analysis of setups.
    
    Responsibilities:
    - Multi-timeframe analysis (1m, 5m, 15m, 1h, 4h)
    - Support/Resistance identification
    - Trend analysis
    - Entry/Exit quality scoring with regime-specific criteria
    - Risk/Reward calculation using Dynamic Protection Manager
    - SL/TP calculation based on regime base protections
    """
    
    def __init__(self):
        self.logger = logging.getLogger("algogpt.technical_analyst")
        self.logger.info("Technical Analyst Scout initialized - MTF analysis + Dynamic Protection ready")
    
    def analyze_setup(
        self,
        symbol: str,
        strategy: str,
        market_data: Dict[str, Any],
        multi_tf_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform deep technical analysis on a trade setup.
        
        Args:
            symbol: Trading pair
            strategy: Proposed strategy (LONG/SHORT/GRID)
            market_data: Market data dict
            multi_tf_data: Optional multi-timeframe data
        
        Returns:
            Dict with score, entry_quality, sl_tp_levels, reasoning
        """
        try:
            score = 0.0
            reasons = []
            
            price = market_data.get("price", 0)
            atr = market_data.get("atr", price * 0.02)
            
            tf_alignment = 0
            if multi_tf_data:
                for tf, data in multi_tf_data.items():
                    trend = data.get("trend", "neutral")
                    if strategy == "LONG" and trend == "bullish":
                        tf_alignment += 1
                    elif strategy == "SHORT" and trend == "bearish":
                        tf_alignment += 1
                
                if tf_alignment >= 3:
                    score += 2.0
                    reasons.append(f"התאמת {tf_alignment} TFs")
                elif tf_alignment >= 2:
                    score += 1.0
                    reasons.append(f"התאמת {tf_alignment} TFs")
            
            support = market_data.get("support_level", price * 0.97)
            resistance = market_data.get("resistance_level", price * 1.03)
            
            if strategy == "LONG":
                distance_to_support = (price - support) / price * 100
                if distance_to_support < 0.5:
                    score += 1.5
                    reasons.append(f"קרוב לתמיכה ${support:.2f}")
                
                distance_to_resistance = (resistance - price) / price * 100
                if distance_to_resistance > 2:
                    score += 1.0
                    reasons.append(f"מרחק טוב להתנגדות +{distance_to_resistance:.1f}%")
            
            elif strategy == "SHORT":
                distance_to_resistance = (resistance - price) / price * 100
                if distance_to_resistance < 0.5:
                    score += 1.5
                    reasons.append(f"קרוב להתנגדות ${resistance:.2f}")
                
                distance_to_support = (price - support) / price * 100
                if distance_to_support > 2:
                    score += 1.0
                    reasons.append(f"מרחק טוב לתמיכה -{distance_to_support:.1f}%")
            
            ema_20 = market_data.get("ema_20", price)
            ema_50 = market_data.get("ema_50", price)
            
            if strategy == "LONG" and price > ema_20 > ema_50:
                score += 1.0
                reasons.append("EMAs בסדר עולה")
            elif strategy == "SHORT" and price < ema_20 < ema_50:
                score += 1.0
                reasons.append("EMAs בסדר יורד")
            
            bb_upper = market_data.get("bb_upper", price * 1.02)
            bb_lower = market_data.get("bb_lower", price * 0.98)
            bb_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
            
            if strategy == "LONG" and bb_position < 0.3:
                score += 0.8
                reasons.append("קרוב לBB תחתון")
            elif strategy == "SHORT" and bb_position > 0.7:
                score += 0.8
                reasons.append("קרוב לBB עליון")
            
            score = max(0, min(10, score))
            
            regime_indicators = {
                "adx": market_data.get("adx", 0),
                "atr": atr / price * 100 if price > 0 else 2.0,
                "bb_width": (bb_upper - bb_lower) / price * 100 if price > 0 else 0,
                "price_range_pct": market_data.get("price_change_24h_pct", 0)
            }
            regime = regime_detector.detect_regime(regime_indicators)
            
            base_protection = protection_manager.get_base_protection(regime)
            
            sl_multiplier = base_protection["sl_atr_multiplier"]
            tp_rr = base_protection["tp_rr_ratio"]
            
            if strategy == "LONG":
                sl_price = price - (atr * sl_multiplier)
                tp_price = price + ((price - sl_price) * tp_rr)
            elif strategy == "SHORT":
                sl_price = price + (atr * sl_multiplier)
                tp_price = price - ((sl_price - price) * tp_rr)
            else:
                sl_price = support if strategy == "LONG" else resistance
                tp_price = resistance if strategy == "LONG" else support
            
            risk = abs(price - sl_price)
            reward = abs(tp_price - price)
            rr_ratio = reward / risk if risk > 0 else 0
            
            if rr_ratio >= 2.0:
                score += 0.5
                reasons.append(f"RR מצוין {rr_ratio:.1f}:1")
            
            reasoning = " | ".join(reasons) if reasons else "אין הצדקה טכנית ברורה"
            
            self.logger.debug(
                f"{symbol} {strategy}: Technical score={score:.1f}, regime={regime}, "
                f"RR={rr_ratio:.1f}:1, SL=ATR×{sl_multiplier}, TP=RR{tp_rr}, reasons={len(reasons)}"
            )
            
            return {
                "scout": "Technical Analyst",
                "symbol": symbol,
                "score": round(score, 1),
                "strategy": strategy,
                "market_regime": regime,
                "reasoning": reasoning,
                "entry_quality": "EXCELLENT" if score >= 7.5 else "GOOD" if score >= 6.0 else "FAIR",
                "sl_price": round(sl_price, 2),
                "tp_price": round(tp_price, 2),
                "risk_reward": round(rr_ratio, 2),
                "sl_atr_multiplier": sl_multiplier,
                "tp_rr_target": tp_rr,
                "base_leverage": int(base_protection["default_leverage"]),
                "confidence": "HIGH" if score >= 7.0 else "MEDIUM" if score >= 5.5 else "LOW"
            }
            
        except Exception as e:
            self.logger.error(f"Failed to analyze {symbol}: {e}", exc_info=True)
            return {
                "scout": "Technical Analyst",
                "symbol": symbol,
                "score": 0,
                "strategy": strategy,
                "reasoning": f"שגיאה: {e}",
                "entry_quality": "POOR",
                "confidence": "LOW"
            }


_market_scanner: Optional[MarketScanner] = None
_technical_analyst: Optional[TechnicalAnalyst] = None


def get_market_scanner() -> MarketScanner:
    """Get or create Market Scanner instance."""
    global _market_scanner
    if _market_scanner is None:
        _market_scanner = MarketScanner()
    return _market_scanner


def get_technical_analyst() -> TechnicalAnalyst:
    """Get or create Technical Analyst instance."""
    global _technical_analyst
    if _technical_analyst is None:
        _technical_analyst = TechnicalAnalyst()
    return _technical_analyst


__all__ = ["MarketScanner", "TechnicalAnalyst", "get_market_scanner", "get_technical_analyst"]
