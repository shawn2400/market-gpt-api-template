"""
Adaptive AI Prompts System
===========================
Dynamic prompt generation based on real-time market conditions.

Each market regime gets optimized prompts for maximum RR and quality.

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
from typing import Dict
from utils.market_intelligence import MarketCondition

LOGGER = logging.getLogger("adaptive_prompts")


class AdaptivePromptEngine:
    """
    Generates AI prompts dynamically based on market intelligence.
    
    Strategy:
    - Trending Bullish → Aggressive long setups, breakouts
    - Trending Bearish → Aggressive short setups, breakdowns
    - Sideways → GRID trading recommendations
    - Choppy → Ultra-selective, high-quality only
    - Volatile → Wait or extreme caution
    """
    
    def __init__(self):
        self.logger = LOGGER
    
    def generate_prompt(
        self, 
        market_condition: MarketCondition,
        symbol: str,
        context: Dict
    ) -> str:
        """
        Generate optimized AI prompt based on current market regime.
        
        Args:
            market_condition: Current market intelligence
            symbol: Trading symbol
            context: Technical analysis data
            
        Returns:
            Tailored AI prompt for this specific market condition
        """
        regime = market_condition.regime
        mood = market_condition.mood
        strategy = market_condition.recommended_strategy
        min_rr = market_condition.min_rr_threshold
        
        # Route to appropriate prompt builder
        if strategy == "wait":
            return self._prompt_wait_mode(symbol, regime, min_rr)
        
        if strategy == "grid":
            return self._prompt_grid_mode(symbol, context, min_rr)
        
        if strategy == "futures_long":
            return self._prompt_futures_long(symbol, context, regime, min_rr)
        
        if strategy == "futures_short":
            return self._prompt_futures_short(symbol, context, regime, min_rr)
        
        # Fallback to conservative prompt
        return self._prompt_conservative(symbol, min_rr)
    
    def _prompt_futures_long(
        self, 
        symbol: str, 
        context: Dict,
        regime: str,
        min_rr: float
    ) -> str:
        """Optimized prompt for bullish trending markets"""
        
        prompt = f"""You are analyzing {symbol} in a BULLISH TRENDING market.

**MARKET REGIME: TRENDING UP ↗️**
**STRATEGY: FUTURES LONG (breakouts, pullbacks)**
**MINIMUM RR REQUIRED: {min_rr:.2f} (TARGET: ≥{min_rr + 0.3:.2f})**

**YOUR MISSION:**
Find HIGH-QUALITY LONG setups with excellent risk/reward.

**WHAT TO LOOK FOR:**
✅ Price above key EMAs (20, 50, 200)
✅ Strong bullish momentum (RSI 50-70, positive MACD)
✅ Clean support levels for tight stop loss
✅ Clear resistance levels for take profit targets
✅ Breakout confirmations or healthy pullbacks to support

**STRICT RR REQUIREMENTS:**
⚠️ **MANDATORY: RR ≥ {min_rr:.2f} MINIMUM**
🎯 **TARGET: RR ≥ {min_rr + 0.3:.2f} for best quality**

**EXAMPLES OF PASS/REJECT:**

✅ PASS: Entry=100, SL=98, TP=106.5 → RR=3.25 (EXCELLENT!)
✅ PASS: Entry=100, SL=97.5, TP=107 → RR=2.80 (GREAT!)
✅ PASS: Entry=100, SL=98, TP=105 → RR=2.50 (GOOD!)
✅ PASS: Entry=100, SL=97, TP=104 → RR=2.33 (ACCEPTABLE)

❌ REJECT: Entry=100, SL=97, TP=102 → RR=0.67 (TOO WEAK!)
❌ REJECT: Entry=100, SL=98.5, TP=101.5 → RR=1.00 (INSUFFICIENT!)
❌ REJECT: Entry=100, SL=98, TP=102 → RR=1.00 (BELOW MINIMUM!)

**DECISION PROCESS:**
1. Is there a clear bullish setup? (YES/NO)
2. Can you place a tight SL below support? (YES/NO)
3. Is there clear upside target resistance? (YES/NO)
4. Does RR ≥ {min_rr:.2f}? **MANDATORY!** (YES/NO)
5. Is success probability realistic (50-85%)? (YES/NO)

**IF ALL "YES" → Propose the trade with EXACT levels**
**IF ANY "NO" → Return {{"proposal": false}} and explain why**

Remember: We want LARGE PROFITS, MINIMAL LOSSES. Quality over quantity!
"""
        return prompt
    
    def _prompt_futures_short(
        self, 
        symbol: str, 
        context: Dict,
        regime: str,
        min_rr: float
    ) -> str:
        """Optimized prompt for bearish trending markets"""
        
        prompt = f"""You are analyzing {symbol} in a BEARISH TRENDING market.

**MARKET REGIME: TRENDING DOWN ↘️**
**STRATEGY: FUTURES SHORT (breakdowns, pullbacks)**
**MINIMUM RR REQUIRED: {min_rr:.2f} (TARGET: ≥{min_rr + 0.3:.2f})**

**YOUR MISSION:**
Find HIGH-QUALITY SHORT setups with excellent risk/reward.

**WHAT TO LOOK FOR:**
✅ Price below key EMAs (20, 50, 200)
✅ Strong bearish momentum (RSI 30-50, negative MACD)
✅ Clean resistance levels for tight stop loss
✅ Clear support levels for take profit targets
✅ Breakdown confirmations or bearish pullbacks to resistance

**STRICT RR REQUIREMENTS:**
⚠️ **MANDATORY: RR ≥ {min_rr:.2f} MINIMUM**
🎯 **TARGET: RR ≥ {min_rr + 0.3:.2f} for best quality**

**EXAMPLES OF PASS/REJECT:**

✅ PASS: Entry=100, SL=102, TP=93.5 → RR=3.25 (EXCELLENT!)
✅ PASS: Entry=100, SL=102.5, TP=93 → RR=2.80 (GREAT!)
✅ PASS: Entry=100, SL=102, TP=95 → RR=2.50 (GOOD!)

❌ REJECT: Entry=100, SL=103, TP=98 → RR=0.67 (TOO WEAK!)
❌ REJECT: Entry=100, SL=102, TP=99 → RR=0.50 (UNACCEPTABLE!)

**DECISION PROCESS:**
1. Is there a clear bearish setup? (YES/NO)
2. Can you place a tight SL above resistance? (YES/NO)
3. Is there clear downside target support? (YES/NO)
4. Does RR ≥ {min_rr:.2f}? **MANDATORY!** (YES/NO)
5. Is success probability realistic (50-85%)? (YES/NO)

**IF ALL "YES" → Propose the trade with EXACT levels**
**IF ANY "NO" → Return {{"proposal": false}} and explain why**

Remember: We want LARGE PROFITS, MINIMAL LOSSES. Quality over quantity!
"""
        return prompt
    
    def _prompt_grid_mode(
        self, 
        symbol: str, 
        context: Dict,
        min_rr: float
    ) -> str:
        """Optimized prompt for sideways/ranging markets"""
        
        prompt = f"""You are analyzing {symbol} in a SIDEWAYS/RANGING market.

**MARKET REGIME: SIDEWAYS ↔️ (Perfect for GRID Trading)**
**STRATEGY: FUTURES GRID (profit from range-bound movement)**
**QUALITY THRESHOLD: Strong support/resistance levels required**

**YOUR MISSION:**
Identify if this symbol is suitable for GRID trading.

**WHAT TO LOOK FOR:**
✅ Clear horizontal support and resistance zones
✅ Price bouncing within a defined range
✅ Weak trend (ADX < 20)
✅ Good liquidity and volume
✅ Range width ≥ 3-5% for profitable grids

**GRID TRADING CRITERIA:**
1. **Range Boundaries:** Clear upper and lower bounds
2. **Range Width:** At least 3% between support/resistance
3. **Price Behavior:** Multiple touches of support/resistance
4. **No Breakout:** Price staying within range (not trending)

**DECISION PROCESS:**
1. Is price clearly range-bound? (YES/NO)
2. Can you identify strong support/resistance? (YES/NO)
3. Is range width ≥ 3%? (YES/NO)
4. Is ADX weak (< 25)? (YES/NO)

**IF ALL "YES" → Recommend GRID trading setup**
**IF ANY "NO" → Return {{"proposal": false}} - suggest waiting for clear trend or range**

**FOR GRID SETUPS:**
- Specify: range_low, range_high, grid_levels (5-10)
- Success probability for range-bound: 60-75%

**ALTERNATIVELY:** If you see a strong directional setup forming (breakout imminent), 
you can propose a regular LONG/SHORT trade instead with RR ≥ {min_rr:.2f}.

Remember: GRID works best in stable ranges. If market is choppy or about to break out, WAIT!
"""
        return prompt
    
    def _prompt_wait_mode(
        self, 
        symbol: str,
        regime: str,
        min_rr: float
    ) -> str:
        """Ultra-conservative prompt for unclear/volatile markets"""
        
        prompt = f"""You are analyzing {symbol} in a UNCERTAIN/VOLATILE market.

**MARKET REGIME: {regime.upper()} ⚠️**
**STRATEGY: ULTRA-SELECTIVE (wait for exceptional setups only)**
**MINIMUM RR REQUIRED: {min_rr + 0.2:.2f} (HIGHER threshold due to uncertainty)**

**SITUATION:**
Market conditions are unclear or too volatile. We need EXCEPTIONAL setups only.

**WHAT TO LOOK FOR:**
🔍 Only crystal-clear, textbook-perfect setups
🔍 Very strong technical confluence
🔍 Obvious support/resistance levels
🔍 Extreme RR ratios (≥ {min_rr + 0.5:.2f} preferred)

**STRICT REQUIREMENTS:**
⚠️ **MANDATORY: RR ≥ {min_rr + 0.2:.2f} (higher than normal)**
⚠️ **Multiple confirmations required**
⚠️ **Very high confidence only (>75%)**

**DECISION PROCESS:**
1. Is this a TEXTBOOK-PERFECT setup? (YES/NO)
2. Is RR ≥ {min_rr + 0.2:.2f}? **MANDATORY!** (YES/NO)
3. Is confidence >75%? (YES/NO)

**IF ALL "YES" → Propose (rare but possible)**
**IF ANY "NO" → Return {{"proposal": false}} - WAIT for better conditions**

**MOST LIKELY OUTCOME:** {{"proposal": false}}

Remember: In uncertain markets, PATIENCE is our best strategy. 
Better to wait than force trades in poor conditions!
"""
        return prompt
    
    def _prompt_conservative(self, symbol: str, min_rr: float) -> str:
        """Fallback conservative prompt"""
        
        prompt = f"""You are analyzing {symbol} with CONSERVATIVE parameters.

**MINIMUM RR REQUIRED: {min_rr:.2f}**
**QUALITY FOCUS: Only high-probability setups**

Analyze the technical data and propose a trade ONLY if:
1. Clear directional setup exists
2. RR ≥ {min_rr:.2f} (MANDATORY)
3. Success probability 50-85%

If conditions aren't ideal, return {{"proposal": false}}.

Quality over quantity. We want LARGE PROFITS, MINIMAL LOSSES.
"""
        return prompt


# Global instance
_adaptive_prompt_engine = None

def get_adaptive_prompt_engine() -> AdaptivePromptEngine:
    """Get singleton instance of AdaptivePromptEngine"""
    global _adaptive_prompt_engine
    if _adaptive_prompt_engine is None:
        _adaptive_prompt_engine = AdaptivePromptEngine()
    return _adaptive_prompt_engine
