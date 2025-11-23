#!/usr/bin/env python3
"""
Technical-Only Trade Generator - Zero AI Dependencies
=======================================================
Generates trade proposals based PURELY on technical levels:
- Support/Resistance levels
- ATR-based SL/TP
- Risk/Reward ratios
- EMA direction

NO API calls, NO AI providers, runs 24/7 offline.
Perfect fallback when AI providers are unavailable.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("algogpt.technical_trade")

@dataclass
class TechnicalTrade:
    """Technical-based trade proposal"""
    symbol: str
    side: str  # LONG or SHORT
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    leverage: int = 10
    success_pct: float = 60.0  # Conservative default
    reason: str = "Technical analysis"
    confidence: float = 65.0
    quality_score: float = 6.5


class TechnicalTradeGenerator:
    """Pure technical trade generation - NO AI NEEDED"""
    
    def __init__(self):
        self.logger = logger
        self.logger.info("🔧 Technical Trade Generator initialized (NO AI REQUIRED)")
    
    def generate_trade(
        self,
        symbol: str,
        price: float,
        indicators: Dict[str, Any],
        side: str = "LONG"
    ) -> Optional[TechnicalTrade]:
        """
        Generate trade proposal using PURE TECHNICAL LEVELS.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            price: Current price
            indicators: Dict with ATR, RSI, EMA, Support/Resistance
            side: LONG or SHORT
            
        Returns:
            TechnicalTrade or None if conditions not met
        """
        # Extract indicators with safe defaults
        atr = float(indicators.get("atr", price * 0.02))  # Default 2% of price
        rsi = float(indicators.get("rsi", 50))
        ema_20 = float(indicators.get("ema_20", price))
        ema_50 = float(indicators.get("ema_50", price))
        adx = float(indicators.get("adx", 20))
        volatility = float(indicators.get("volatility", 5))
        
        # Support/Resistance levels (if provided)
        support = float(indicators.get("support", price * 0.95))
        resistance = float(indicators.get("resistance", price * 1.05))
        
        # ========== ENTRY & SL/TP CALCULATION ==========
        
        if side == "LONG":
            # Entry: At price or slightly above EMA20
            entry = max(price, ema_20 * 0.999)  # Slight buffer below EMA20
            
            # Stop Loss: Below support or 2x ATR below entry
            sl_below_support = support * 0.98
            sl_below_atr = entry - (atr * 2.0)
            sl = min(sl_below_support, sl_below_atr)
            
            # Take Profit: 1.5x-2.0x risk above entry
            risk = entry - sl
            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 2.0)
            tp3 = entry + (risk * 2.5)
            
            # Confidence based on EMA alignment + RSI
            if ema_20 > ema_50 and rsi < 70:  # Perfect LONG conditions
                confidence = 75.0
                quality = 7.5
                reason = f"LONG: Price above EMA (bullish), RSI={rsi:.0f} (not overbought), strong ATR={atr:.8f}"
            elif ema_20 > ema_50:
                confidence = 65.0
                quality = 6.5
                reason = f"LONG: Price above EMA (bullish), RSI={rsi:.0f} (extreme), moderate risk"
            elif rsi < 30:  # Oversold bounce
                confidence = 60.0
                quality = 6.0
                reason = f"LONG: Oversold bounce (RSI={rsi:.0f}), potential reversal"
            else:
                confidence = 50.0
                quality = 5.0
                reason = f"LONG: Neutral conditions, lower confidence"
        
        else:  # SHORT
            # Entry: At price or slightly below EMA20
            entry = min(price, ema_20 * 1.001)  # Slight buffer above EMA20
            
            # Stop Loss: Above resistance or 2x ATR above entry
            sl_above_resistance = resistance * 1.02
            sl_above_atr = entry + (atr * 2.0)
            sl = max(sl_above_resistance, sl_above_atr)
            
            # Take Profit: 1.5x-2.0x risk below entry
            risk = sl - entry
            tp1 = entry - (risk * 1.5)
            tp2 = entry - (risk * 2.0)
            tp3 = entry - (risk * 2.5)
            
            # Confidence based on EMA alignment + RSI
            if ema_20 < ema_50 and rsi > 30:  # Perfect SHORT conditions
                confidence = 75.0
                quality = 7.5
                reason = f"SHORT: Price below EMA (bearish), RSI={rsi:.0f} (not oversold), strong ATR={atr:.8f}"
            elif ema_20 < ema_50:
                confidence = 65.0
                quality = 6.5
                reason = f"SHORT: Price below EMA (bearish), RSI={rsi:.0f} (extreme), moderate risk"
            elif rsi > 70:  # Overbought bounce
                confidence = 60.0
                quality = 6.0
                reason = f"SHORT: Overbought bounce (RSI={rsi:.0f}), potential reversal"
            else:
                confidence = 50.0
                quality = 5.0
                reason = f"SHORT: Neutral conditions, lower confidence"
        
        # ========== RISK VALIDATION ==========
        
        # Calculate Risk/Reward
        risk = abs(entry - sl)
        reward1 = abs(tp1 - entry)
        rr = reward1 / risk if risk > 0 else 0
        
        # Minimum RR check
        if rr < 0.8:
            self.logger.info(f"🚫 {symbol} REJECTED: Poor RR ratio ({rr:.2f} < 0.8)")
            return None
        
        # Volatility check - skip if too high
        if volatility > 12 and adx < 25:
            confidence *= 0.7  # Reduce confidence in unstable markets
            reason += " (volatile conditions, reduced confidence)"
        
        # Success percentage (conservative)
        success_pct = max(35.0, min(75.0, confidence * 0.8))
        
        return TechnicalTrade(
            symbol=symbol,
            side=side,
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2 if tp2 > 0 else None,
            tp3=tp3 if tp3 > 0 else None,
            leverage=max(2, min(15, int(10 * (quality / 7.0)))),  # Dynamic leverage
            success_pct=success_pct,
            reason=reason,
            confidence=confidence,
            quality_score=quality
        )


# ============ SINGLETON INSTANCE ============
_generator = None

def get_technical_trade_generator() -> TechnicalTradeGenerator:
    """Get or create singleton instance"""
    global _generator
    if _generator is None:
        _generator = TechnicalTradeGenerator()
    return _generator
