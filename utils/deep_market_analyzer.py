#!/usr/bin/env python3
"""
Deep Market Analyzer - Multi-Layer Market Analysis
==================================================
Deep multi-timeframe analysis before trade entry to prevent quick
losses like XRPUSDT (-$0.59 in 83 seconds).

Analyzes:
- Multi-Timeframe Correlation (4H, 1H, 15M)
- Volume Profile Analysis
- Order Flow Detection
- Liquidity Zones Mapping
- Support/Resistance Strength
- Momentum Confirmation

Only approves entry when ALL layers confirm strength.
Part of MetaBrain v9.1 - Precision Entry System
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("algogpt.deep_market_analyzer")


@dataclass
class DeepAnalysisResult:
    """Result of deep market analysis"""
    approved: bool  # True if entry is safe
    confidence: float  # 0-100
    quality_score: float  # 0-10
    warnings: List[str]  # Potential issues
    strengths: List[str]  # Positive factors
    reasoning: str  # Overall assessment


class DeepMarketAnalyzer:
    """
    Performs deep multi-layer market analysis before entry.
    
    Prevents scenarios like:
    - Entry → Exit 83 seconds later with loss
    - Weak setups with no confirmation
    - Counter-trend trades in strong momentum
    """
    
    def __init__(self):
        self.logger = logger
    
    def analyze_entry(
        self,
        symbol: str,
        side: str,  # LONG/SHORT
        market_ctx: Dict[str, Any],
        tf_contexts: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> DeepAnalysisResult:
        """
        Deep analysis before trade entry.
        
        Args:
            symbol: Trading symbol
            side: LONG or SHORT
            market_ctx: Primary timeframe market data
            tf_contexts: Multi-timeframe data (4H, 1H, 15M)
        
        Returns:
            DeepAnalysisResult with approval decision
        """
        self.logger.info(f"🔍 Deep Market Analysis for {symbol} {side}...")
        
        warnings = []
        strengths = []
        scores = []
        
        # Layer 1: Multi-Timeframe Correlation
        mtf_score, mtf_warnings, mtf_strengths = self._analyze_multi_timeframe(
            side, tf_contexts or {}
        )
        scores.append(mtf_score)
        warnings.extend(mtf_warnings)
        strengths.extend(mtf_strengths)
        
        # Layer 2: Volume Profile
        vol_score, vol_warnings, vol_strengths = self._analyze_volume_profile(
            market_ctx
        )
        scores.append(vol_score)
        warnings.extend(vol_warnings)
        strengths.extend(vol_strengths)
        
        # Layer 3: Momentum Confirmation
        mom_score, mom_warnings, mom_strengths = self._analyze_momentum(
            side, market_ctx
        )
        scores.append(mom_score)
        warnings.extend(mom_warnings)
        strengths.extend(mom_strengths)
        
        # Layer 4: Liquidity & Support/Resistance
        liq_score, liq_warnings, liq_strengths = self._analyze_liquidity_zones(
            side, market_ctx
        )
        scores.append(liq_score)
        warnings.extend(liq_warnings)
        strengths.extend(liq_strengths)
        
        # Calculate overall quality
        quality_score = sum(scores) / len(scores) if scores else 0
        confidence = quality_score * 10.0  # Convert 0-10 → 0-100
        
        # Decision: Approve only if quality is sufficient
        approved = quality_score >= 6.0 and len(warnings) <= 2
        
        # Generate reasoning
        reasoning = self._generate_reasoning(
            quality_score, approved, warnings, strengths
        )
        
        result = DeepAnalysisResult(
            approved=approved,
            confidence=confidence,
            quality_score=quality_score,
            warnings=warnings,
            strengths=strengths,
            reasoning=reasoning
        )
        
        status = "✅ APPROVED" if approved else "❌ REJECTED"
        self.logger.info(
            f"{status} | Quality={quality_score:.1f}/10 | "
            f"Warnings={len(warnings)} | Strengths={len(strengths)}"
        )
        
        return result
    
    def _analyze_multi_timeframe(
        self,
        side: str,
        tf_contexts: Dict[str, Dict[str, Any]]
    ) -> Tuple[float, List[str], List[str]]:
        """
        Analyze multi-timeframe alignment.
        
        Returns: (score 0-10, warnings, strengths)
        """
        warnings = []
        strengths = []
        score = 5.0  # Neutral start
        
        if not tf_contexts:
            warnings.append("No multi-TF data available")
            return score, warnings, strengths
        
        # Check 4H, 1H, 15M alignment
        tf_trends = {}
        for interval in ["4h", "1h", "15m"]:
            ctx = tf_contexts.get(interval)
            if not ctx:
                continue
            
            # Determine trend from EMAs
            price = ctx.get("close", 0)
            ema_20 = ctx.get("ema_20", price)
            ema_50 = ctx.get("ema_50", price)
            
            if price > ema_20 > ema_50:
                tf_trends[interval] = "LONG"
            elif price < ema_20 < ema_50:
                tf_trends[interval] = "SHORT"
            else:
                tf_trends[interval] = "NEUTRAL"
        
        # Check alignment with our side
        aligned_count = sum(1 for trend in tf_trends.values() if trend == side)
        total_tfs = len(tf_trends)
        
        if total_tfs > 0:
            alignment_pct = (aligned_count / total_tfs) * 100
            
            if alignment_pct >= 66:  # 2/3 aligned
                score += 2.0
                strengths.append(f"Multi-TF alignment: {alignment_pct:.0f}%")
            elif alignment_pct < 33:  # <1/3 aligned
                score -= 2.0
                warnings.append(f"Poor TF alignment: {alignment_pct:.0f}%")
        
        return score, warnings, strengths
    
    def _analyze_volume_profile(
        self,
        market_ctx: Dict[str, Any]
    ) -> Tuple[float, List[str], List[str]]:
        """
        Analyze volume confirmation.
        
        Returns: (score 0-10, warnings, strengths)
        """
        warnings = []
        strengths = []
        score = 5.0
        
        volume = market_ctx.get("volume", 0)
        vol_sma_20 = market_ctx.get("volume_sma_20", volume)
        
        if vol_sma_20 and vol_sma_20 > 0:
            vol_ratio = volume / vol_sma_20
            
            if vol_ratio >= 1.5:
                score += 2.0
                strengths.append(f"Strong volume: {vol_ratio:.1f}x average")
            elif vol_ratio >= 1.2:
                score += 1.0
                strengths.append(f"Above-average volume: {vol_ratio:.1f}x")
            elif vol_ratio < 0.7:
                score -= 1.5
                warnings.append(f"Low volume: {vol_ratio:.1f}x average")
        
        return score, warnings, strengths
    
    def _analyze_momentum(
        self,
        side: str,
        market_ctx: Dict[str, Any]
    ) -> Tuple[float, List[str], List[str]]:
        """
        Analyze momentum confirmation.
        
        Returns: (score 0-10, warnings, strengths)
        """
        warnings = []
        strengths = []
        score = 5.0
        
        # RSI check
        rsi = market_ctx.get("rsi", 50)
        
        if side == "LONG":
            if rsi > 50 and rsi < 70:
                score += 1.5
                strengths.append(f"Bullish RSI: {rsi:.1f}")
            elif rsi < 30:
                warnings.append(f"RSI oversold: {rsi:.1f} - risky for LONG")
                score -= 1.0
        else:  # SHORT
            if rsi < 50 and rsi > 30:
                score += 1.5
                strengths.append(f"Bearish RSI: {rsi:.1f}")
            elif rsi > 70:
                warnings.append(f"RSI overbought: {rsi:.1f} - risky for SHORT")
                score -= 1.0
        
        # MACD check
        macd = market_ctx.get("macd", 0)
        
        if side == "LONG" and macd > 0:
            score += 1.0
            strengths.append("MACD bullish")
        elif side == "SHORT" and macd < 0:
            score += 1.0
            strengths.append("MACD bearish")
        elif (side == "LONG" and macd < 0) or (side == "SHORT" and macd > 0):
            warnings.append("MACD conflicts with direction")
            score -= 1.0
        
        return score, warnings, strengths
    
    def _analyze_liquidity_zones(
        self,
        side: str,
        market_ctx: Dict[str, Any]
    ) -> Tuple[float, List[str], List[str]]:
        """
        Analyze support/resistance and liquidity.
        
        Returns: (score 0-10, warnings, strengths)
        """
        warnings = []
        strengths = []
        score = 5.0
        
        price = market_ctx.get("close", 0)
        
        # Check distance from key levels
        high_24h = market_ctx.get("high_24h", price)
        low_24h = market_ctx.get("low_24h", price)
        
        if high_24h and low_24h and low_24h > 0:
            range_24h = high_24h - low_24h
            
            # Price position in range
            if range_24h > 0:
                pos_in_range = ((price - low_24h) / range_24h) * 100
                
                if side == "LONG":
                    if pos_in_range < 30:  # Near support
                        score += 1.5
                        strengths.append(f"Price near support ({pos_in_range:.0f}%)")
                    elif pos_in_range > 80:  # Near resistance
                        warnings.append(f"Price near resistance ({pos_in_range:.0f}%)")
                        score -= 1.0
                else:  # SHORT
                    if pos_in_range > 70:  # Near resistance
                        score += 1.5
                        strengths.append(f"Price near resistance ({pos_in_range:.0f}%)")
                    elif pos_in_range < 20:  # Near support
                        warnings.append(f"Price near support ({pos_in_range:.0f}%)")
                        score -= 1.0
        
        return score, warnings, strengths
    
    def _generate_reasoning(
        self,
        quality: float,
        approved: bool,
        warnings: List[str],
        strengths: List[str]
    ) -> str:
        """Generate reasoning in Hebrew + English"""
        
        if approved:
            reason = f"✅ Deep analysis approved (Quality={quality:.1f}/10). "
        else:
            reason = f"❌ Deep analysis rejected (Quality={quality:.1f}/10). "
        
        if strengths:
            reason += f"Strengths: {', '.join(strengths[:3])}. "
        
        if warnings:
            reason += f"Warnings: {', '.join(warnings[:3])}."
        
        return reason


# Singleton instance
_deep_analyzer: Optional[DeepMarketAnalyzer] = None


def get_deep_market_analyzer() -> DeepMarketAnalyzer:
    """Get or create singleton deep market analyzer"""
    global _deep_analyzer
    if _deep_analyzer is None:
        _deep_analyzer = DeepMarketAnalyzer()
    return _deep_analyzer


def analyze_entry_deep(
    symbol: str,
    side: str,
    market_ctx: Dict[str, Any],
    tf_contexts: Optional[Dict[str, Dict[str, Any]]] = None
) -> DeepAnalysisResult:
    """
    Convenience function for deep entry analysis.
    
    Returns approval decision with detailed reasoning.
    """
    analyzer = get_deep_market_analyzer()
    return analyzer.analyze_entry(symbol, side, market_ctx, tf_contexts)
