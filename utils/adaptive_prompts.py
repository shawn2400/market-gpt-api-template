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
        
        prompt = f"""You are analyzing {symbol} in a BULLISH TRENDING market. Return ONLY JSON.

**🚀 MARKET REGIME: TRENDING UP ↗️ (MOMENTUM STRATEGY)**
**💎 STRATEGY: FUTURES LONG - Ride the trend with quality entries**
**✅ MINIMUM RR: {min_rr:.2f} (TARGET: ≥{min_rr + 0.4:.2f} for trending markets)**

**YOUR MISSION:**
Catch bullish momentum with smart entries and realistic targets.

**🎯 TRENDING MARKET = OPPORTUNITY FOR BIGGER MOVES:**
In trending markets, we can aim for LARGER profits with slightly wider stops.
Look for pullbacks to support, breakout confirmations, momentum continuations.

**WHAT TO LOOK FOR:**
✅ **Price Structure**: Above key EMAs (20/50), higher highs/higher lows
✅ **Momentum Confirmation**: RSI 50-70, positive MACD, volume increasing
✅ **Entry Point**: Pullback to support OR breakout above resistance
✅ **Stop Placement**: Below recent swing low or key support (1.5-3% typical)
✅ **Target Selection**: Next resistance, fibonacci extension, recent high

**STRICT RR REQUIREMENTS:**
⚠️ **MANDATORY: RR ≥ {min_rr:.2f}** (trending allows bigger targets!)
🎯 **TARGET: RR ≥ {min_rr + 0.4:.2f}** (aim for 1.6-2.5+ in trends)

**✅ EXAMPLES OF QUALITY TRENDING SETUPS:**

EXCELLENT ✅: Entry=100, SL=97.5 (2.5%), TP=106 (6%) → RR=2.40 (RIDE THE TREND!)
GREAT ✅: Entry=100, SL=98 (2%), TP=104.5 (4.5%) → RR=2.25 (STRONG!)
GOOD ✅: Entry=100, SL=98.5 (1.5%), TP=103 (3%) → RR=2.00 (SOLID!)
ACCEPTABLE ✅: Entry=100, SL=98 (2%), TP=102.5 (2.5%) → RR=1.25 (MINIMUM!)

REJECT ❌: Entry=100, SL=97, TP=100.5 → RR=0.17 (WEAK TARGET!)
REJECT ❌: Entry=100, SL=98, TP=101 → RR=0.50 (NOT ENOUGH REWARD!)
REJECT ❌: Entry=100, SL=96, TP=103 → RR=0.75 (SL TOO WIDE!)

**🚀 YOUR DECISION PROCESS:**
1. Is trend clearly UP (price > EMAs, higher highs)? (YES/NO)
2. Is there momentum confirmation (RSI/MACD positive)? (YES/NO)
3. Can I enter on pullback to support OR breakout? (YES/NO)
4. Can I place SL below key support (1.5-3% risk)? (YES/NO)
5. Is target realistic at resistance/extension (≥{min_rr:.2f}x risk)? (YES/NO)
6. **Does RR ≥ {min_rr:.2f}?** MANDATORY! (YES/NO)
7. Is success probability honest (50-75%)? (YES/NO)

**IF 6-7 "YES" → PROPOSE THE TRADE!** (Quality trending setup)
**IF 4-5 "YES" → Adjust levels to improve RR**
**IF ≤3 "YES" → Return {{"proposal": false}} - wait for better confirmation**

**💎 TRENDING MARKET PHILOSOPHY:**
Trends = opportunity for LARGER moves (2-6% gains typical)
Ride momentum, but don't chase - wait for pullbacks or confirmations
Quality = clear trend + smart entry + realistic RR ≥ {min_rr:.2f}

Return your analysis in JSON format with exact entry, sl, tp1, tp2, tp3, leverage, success_pct, reason.
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
        
        prompt = f"""You are analyzing {symbol} in a BEARISH TRENDING market. Return ONLY JSON.

**📉 MARKET REGIME: TRENDING DOWN ↘️ (DOWNSIDE MOMENTUM)**
**💎 STRATEGY: FUTURES SHORT - Profit from bearish momentum**
**✅ MINIMUM RR: {min_rr:.2f} (TARGET: ≥{min_rr + 0.4:.2f} for trending markets)**

**YOUR MISSION:**
Catch bearish momentum with smart SHORT entries and realistic profit targets.

**🎯 DOWNTREND = OPPORTUNITY FOR BIGGER SHORT PROFITS:**
Bearish trends can accelerate fast - capture falling knives with smart entries.
Look for resistance rejections, breakdown confirmations, failed rallies.

**WHAT TO LOOK FOR:**
✅ **Price Structure**: Below key EMAs (20/50), lower highs/lower lows
✅ **Momentum Confirmation**: RSI 30-50, negative MACD, volume on drops
✅ **Entry Point**: Pullback to resistance OR breakdown below support
✅ **Stop Placement**: Above recent swing high or key resistance (1.5-3% typical)
✅ **Target Selection**: Next support, fibonacci extension, recent low

**STRICT RR REQUIREMENTS:**
⚠️ **MANDATORY: RR ≥ {min_rr:.2f}** (downtrends allow bigger drop targets!)
🎯 **TARGET: RR ≥ {min_rr + 0.4:.2f}** (aim for 1.6-2.5+ in downtrends)

**✅ EXAMPLES OF QUALITY BEARISH SETUPS:**

EXCELLENT ✅: Entry=100, SL=102.5 (2.5%), TP=94 (6%) → RR=2.40 (CATCH THE DROP!)
GREAT ✅: Entry=100, SL=102 (2%), TP=95.5 (4.5%) → RR=2.25 (STRONG SHORT!)
GOOD ✅: Entry=100, SL=101.5 (1.5%), TP=97 (3%) → RR=2.00 (SOLID!)
ACCEPTABLE ✅: Entry=100, SL=102 (2%), TP=97.5 (2.5%) → RR=1.25 (MINIMUM!)

REJECT ❌: Entry=100, SL=103, TP=99.5 → RR=0.17 (WEAK!)
REJECT ❌: Entry=100, SL=102, TP=99 → RR=0.50 (NOT ENOUGH!)
REJECT ❌: Entry=100, SL=104, TP=97 → RR=0.75 (SL TOO WIDE!)

**🚀 YOUR DECISION PROCESS:**
1. Is trend clearly DOWN (price < EMAs, lower lows)? (YES/NO)
2. Is there momentum confirmation (RSI/MACD negative)? (YES/NO)
3. Can I enter on pullback to resistance OR breakdown? (YES/NO)
4. Can I place SL above key resistance (1.5-3% risk)? (YES/NO)
5. Is target realistic at support/extension (≥{min_rr:.2f}x risk)? (YES/NO)
6. **Does RR ≥ {min_rr:.2f}?** MANDATORY! (YES/NO)
7. Is success probability honest (50-75%)? (YES/NO)

**IF 6-7 "YES" → PROPOSE THE SHORT TRADE!** (Quality bearish setup)
**IF 4-5 "YES" → Adjust levels to improve RR**
**IF ≤3 "YES" → Return {{"proposal": false}} - wait for better setup**

**💎 BEARISH TREND PHILOSOPHY:**
Downtrends = opportunity for FAST profits (drops faster than rallies!)
Short resistance rejections, but don't chase - wait for pullbacks or confirmations
Quality = clear downtrend + smart entry + realistic RR ≥ {min_rr:.2f}

Return your analysis in JSON format with exact entry, sl, tp1, tp2, tp3, leverage, success_pct, reason.
"""
        return prompt
    
    def _prompt_grid_mode(
        self, 
        symbol: str, 
        context: Dict,
        min_rr: float
    ) -> str:
        """Optimized prompt for sideways/ranging/choppy markets - ULTRA-AGGRESSIVE QUALITY MODE"""
        
        prompt = f"""You are analyzing {symbol} in a SIDEWAYS/CHOPPY market. Return ONLY JSON.

**🎯 MARKET REGIME: CHOPPY/SIDEWAYS - YOUR PLAYGROUND! ↔️**
**🚀 MISSION: FIND THE BEST OPPORTUNITIES - NOT ALL, JUST THE BEST!**
**✅ MINIMUM RR: {min_rr:.2f} (LOWERED for more opportunities)**
**💎 QUALITY FOCUS: Best setups only, but EMBRACE this market type!**

**CRITICAL MINDSET:**
CHOPPY markets = OPPORTUNITY! NOT something to avoid!
This is where we make consistent profits with tight, quick trades.
Look for QUALITY bounces, CLEAR levels, TIGHT stops.

**TRADING STRATEGIES FOR CHOPPY MARKETS:**

**🎯 STRATEGY 1: RANGE SCALPING (PRIMARY)**
Perfect for tight ranges with clear S/R:

✅ **WHAT TO LOOK FOR:**
- Price near strong support/resistance (recent bounces there)
- Clear bounce signal: hammer/engulfing candle, RSI divergence, volume spike
- Tight stop possible: 0.5-2% below support (LONG) or above resistance (SHORT)
- Quick target: next S/R level within 1-3% distance
- **RR ≥ {min_rr:.2f}** (1.1-1.5 is EXCELLENT for scalping!)

✅ **EXAMPLE SETUP:**
- Price at 100.0, strong support at 99.5 (multiple bounces)
- Entry: 100.0 (on bullish engulfing)
- SL: 99.2 (0.8% tight stop below support)
- TP: 101.1 (1.1% at resistance)
- **RR: 1.38** ✅ QUALITY SCALP!

**🎯 STRATEGY 2: GRID TRADING (IF CLEAR RANGE)**
For wider ranges with predictable movement:

✅ **WHAT TO LOOK FOR:**
- Clear range boundaries (support + resistance tested 2+ times)
- Range width ≥ 1.5% (lowered threshold)
- Weak directional trend (price oscillating)
- Predictable back-and-forth movement

✅ **GRID CRITERIA:**
If you can identify clear range_low and range_high with ≥1.5% width → Recommend GRID

**🎯 STRATEGY 3: QUICK MEAN-REVERSION**
For overextended moves in ranging market:

✅ **WHAT TO LOOK FOR:**
- Price stretched far from EMA20/50 (>2% deviation)
- RSI overbought (>70) for SHORT or oversold (<30) for LONG
- Clear reversion target back to moving average
- Tight stop beyond recent extreme

**⚠️ MANDATORY QUALITY CHECKS (MUST PASS ALL):**
1. **RR ≥ {min_rr:.2f}** - MANDATORY! Calculate: RR = |entry - tp1| / |entry - sl|
2. **Tight Stop Loss** - Max 2% from entry (tighter is better!)
3. **Clear Levels** - Support/resistance visible in recent price action
4. **Realistic Target** - TP at logical level (not random number)
5. **Success Probability** - 50-75% (be honest, not optimistic!)

**✅ EXAMPLES OF QUALITY CHOPPY SETUPS:**

PASS ✅: Entry=100, SL=99.2 (0.8%), TP=101.1 (1.1%) → RR=1.38 (EXCELLENT SCALP!)
PASS ✅: Entry=100, SL=98.5 (1.5%), TP=102.3 (2.3%) → RR=1.53 (GREAT!)
PASS ✅: Entry=100, SL=99.0 (1.0%), TP=101.2 (1.2%) → RR=1.20 (GOOD TIGHT SCALP!)

REJECT ❌: Entry=100, SL=99.5 (0.5%), TP=100.3 (0.3%) → RR=0.60 (TOO WEAK!)
REJECT ❌: Entry=100, SL=97 (3%), TP=103 (3%) → RR=1.00 (SL TOO WIDE FOR CHOPPY!)

**🚀 YOUR DECISION PROCESS:**
1. Is price at/near strong support or resistance? (YES/NO)
2. Is there a clear bounce/rejection signal? (YES/NO)
3. Can I place tight SL (≤2% from entry)? (YES/NO)
4. Is there a clear nearby target (next S/R level)? (YES/NO)
5. **Does RR ≥ {min_rr:.2f}?** MANDATORY! (YES/NO)
6. Is setup probability realistic (50-75%)? (YES/NO)

**IF 5-6 "YES" → PROPOSE THE TRADE! This is quality in choppy market!**
**IF 3-4 "YES" → Recalculate levels to improve RR**
**IF ≤2 "YES" → Return {{"proposal": false}} - wait for better setup**

**💎 KEY PHILOSOPHY:**
CHOPPY = OPPORTUNITY for tight, frequent profits!
We want THE BEST setups (not random), but we ACTIVELY SEEK them!
Quality ≠ waiting forever. Quality = smart tight stops + clear levels + realistic RR.

**🎯 FINAL REMINDER:**
- RR ≥ {min_rr:.2f} is MANDATORY (1.1-1.5 is EXCELLENT for scalping!)
- Tight stops (0.5-2%) are your FRIEND in choppy markets
- Clear S/R levels = MUST (not guessing random numbers)
- If you see a QUALITY setup → TAKE IT! Don't overthink!

Return your analysis in JSON format with exact entry, sl, tp1, tp2, tp3, leverage, success_pct, reason.
"""
        return prompt
    
    def _prompt_wait_mode(
        self, 
        symbol: str,
        regime: str,
        min_rr: float
    ) -> str:
        """Ultra-conservative prompt for unclear/volatile markets"""
        
        prompt = f"""You are analyzing {symbol} in a UNCERTAIN/VOLATILE market. Return ONLY JSON.

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
        
        prompt = f"""You are analyzing {symbol} with CONSERVATIVE parameters. Return ONLY JSON.

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
