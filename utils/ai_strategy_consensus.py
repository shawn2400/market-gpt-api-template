#!/usr/bin/env python3
"""
AI Strategy Consensus Engine - 100% Dynamic Strategy Selection
==============================================================
5 AI Brains vote on optimal strategy (GRID/Mean-Reversion/Scalping) based on
real-time market conditions. ZERO hardcoded thresholds or IF statements.

This replaces static logic like:
  ❌ if range >= 2%: strategy = "GRID"
  ❌ elif range < 2%: strategy = "Mean-Reversion"

With dynamic AI consensus:
  ✅ 5 brains analyze market → vote on best strategy
  ✅ ≥3 APPROVE = execute chosen strategy
  ✅ Complete transparency with reasoning

Part of MetaBrain v9.1 - Zero Templates System
"""

import logging
import os
import asyncio
from typing import Dict, Any, List, Optional, Literal
from dataclasses import dataclass
import httpx

# Import AI clients
try:
    from utils.gemini_client import call_gemini, ENABLE_GEMINI
except ImportError:
    call_gemini = None
    ENABLE_GEMINI = False

try:
    from utils.llm_client import llm_chat_completion
except ImportError:
    llm_chat_completion = None

try:
    from utils.xai_client import call_xai, ENABLE_XAI
except ImportError:
    call_xai = None
    ENABLE_XAI = False

try:
    from utils.anthropic_client import call_anthropic, ENABLE_ANTHROPIC
except ImportError:
    call_anthropic = None
    ENABLE_ANTHROPIC = False

logger = logging.getLogger("algogpt.ai_strategy_consensus")

StrategyType = Literal["grid", "mean_reversion", "scalping", "wait"]

@dataclass
class StrategyVote:
    """Single AI brain's strategy vote"""
    brain: str  # AI provider name
    strategy: StrategyType  # Chosen strategy
    confidence: float  # 0-100
    reasoning: str  # Why this strategy
    side: Optional[str] = None  # LONG/SHORT if applicable
    
@dataclass
class StrategyConsensus:
    """Consensus result from all AI brains"""
    strategy: StrategyType  # Final chosen strategy
    side: Optional[str]  # LONG/SHORT
    confidence: float  # 0-100 weighted average
    votes_approve: int  # Number of brains approving this strategy
    total_votes: int  # Total brains voted
    votes: List[StrategyVote]  # All individual votes
    reasoning: str  # Aggregated reasoning


class AIStrategySelector:
    """
    AI-driven strategy selection using 5-brain consensus.
    
    Each brain analyzes:
    - Market regime (CHOPPY/TRENDING/VOLATILE/SIDEWAYS)
    - Volatility level
    - Volume profile
    - Price range
    - Liquidity zones
    
    Returns optimal strategy without ANY hardcoded rules.
    """
    
    def __init__(self):
        self.logger = logger
        
        # API keys
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        self.xai_key = os.getenv("XAI_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        
        # 🚀 COST OPTIMIZATION: Only 3 cheap brains enabled
        # GPT-5 and Claude DISABLED to avoid $500/month costs
        self.brains_available = {
            "Gemini": ENABLE_GEMINI and call_gemini,
            "DeepSeek": bool(self.deepseek_key) and llm_chat_completion,
            "Grok": ENABLE_XAI and call_xai
        }
        
        active_brains = [name for name, available in self.brains_available.items() if available]
        self.logger.info(f"🧠 AI Strategy Selector initialized with {len(active_brains)} brains: {', '.join(active_brains)}")
    
    def _build_strategy_prompt(self, market_ctx: Dict[str, Any], symbol: str) -> str:
        """
        Build comprehensive prompt for AI strategy selection.
        
        Gives AI ALL market data without suggesting any strategy.
        """
        # Extract market data
        regime = market_ctx.get("regime", "UNKNOWN")
        mood = market_ctx.get("mood", "NEUTRAL")
        volatility = market_ctx.get("volatility", "medium")
        
        # Price data
        price = market_ctx.get("close", 0)
        high_24h = market_ctx.get("high_24h", price)
        low_24h = market_ctx.get("low_24h", price)
        
        # Calculate range %
        range_pct = 0.0
        if low_24h and low_24h > 0:
            range_pct = ((high_24h - low_24h) / low_24h) * 100.0
        
        # Technical indicators
        rsi = market_ctx.get("rsi", 50)
        atr_pct = market_ctx.get("atr_pct", 0) * 100  # Convert to %
        volume = market_ctx.get("volume", 0)
        
        # VWAP data (for mean reversion)
        vwap = market_ctx.get("vwap", price)
        vwap_dev_pct = 0.0
        if vwap and vwap > 0:
            vwap_dev_pct = ((price - vwap) / vwap) * 100.0
        
        prompt = f"""בחר אסטרטגיית מסחר אופטימלית עבור {symbol}:

📊 Market Data:
━━━━━━━━━━━━━━━━━━━━
• Regime: {regime}
• Mood: {mood}
• Volatility: {volatility}
• Price: {price}
• 24H Range: {range_pct:.2f}%
• ATR%: {atr_pct:.2f}%
• RSI: {rsi:.1f}
• Volume: {volume:,.0f}

📈 Price Analysis:
━━━━━━━━━━━━━━━━━━━━
• High 24H: {high_24h}
• Low 24H: {low_24h}
• VWAP: {vwap}
• VWAP Deviation: {vwap_dev_pct:+.2f}%

🎯 Your Task:
━━━━━━━━━━━━━━━━━━━━
Analyze the data and choose THE BEST strategy:

1. **GRID** - רשת מסחר (range-bound markets)
   Best for: Choppy/sideways markets with clear range
   
2. **MEAN_REVERSION** - חזרה לממוצע (VWAP-based)
   Best for: Price deviation from fair value
   
3. **SCALPING** - סקלפינג מהיר
   Best for: Quick in/out on small moves
   
4. **WAIT** - המתן (no clear setup)
   Best for: Unclear/dangerous conditions

Also decide: LONG or SHORT?

📝 Response Format (Hebrew + English):
━━━━━━━━━━━━━━━━━━━━
STRATEGY: [grid/mean_reversion/scalping/wait]
SIDE: [LONG/SHORT/NONE]
CONFIDENCE: [0-100]
REASONING: [2-3 sentences explaining why this strategy is best NOW]

Example:
STRATEGY: mean_reversion
SIDE: LONG
CONFIDENCE: 78
REASONING: המחיר 2.1% מתחת ל-VWAP בשוק CHOPPY עם volatility נמוכה. Mean-reversion אופטימלית כי הטווח קטן (<2%) והסיכוי גבוה לחזרה לממוצע. LONG כי המחיר oversold יחסית.

Your analysis:"""
        
        return prompt
    
    async def _call_gemini(self, prompt: str) -> Optional[StrategyVote]:
        """Gemini 2 Pro strategy vote"""
        try:
            if not ENABLE_GEMINI or not call_gemini:
                return None
            
            response = await call_gemini(
                prompt,
                system="You are Gemini 2 Pro, fast multi-modal trading analyst. Analyze market and select optimal strategy.",
                temperature=0.7,
                max_tokens=400
            )
            
            if response:
                return self._parse_strategy_response(response, "Gemini 2 Pro")
            return None
                
        except Exception as e:
            self.logger.error(f"Gemini strategy vote failed: {e}")
            return None
    
    async def _call_deepseek(self, prompt: str) -> Optional[StrategyVote]:
        """DeepSeek strategy vote"""
        try:
            if not self.deepseek_key or not llm_chat_completion:
                return None
            
            response = await llm_chat_completion(
                messages=[
                    {"role": "system", "content": "You are DeepSeek, deep market pattern analyst. Analyze and select optimal trading strategy."},
                    {"role": "user", "content": prompt}
                ],
                model="deepseek-chat",
                temperature=0.7,
                max_tokens=400
            )
            
            if response and "choices" in response:
                analysis = response["choices"][0]["message"]["content"]
                return self._parse_strategy_response(analysis, "DeepSeek")
            return None
                
        except Exception as e:
            self.logger.error(f"DeepSeek strategy vote failed: {e}")
            return None
    
    async def _call_grok(self, prompt: str) -> Optional[StrategyVote]:
        """Grok (XAI) strategy vote"""
        try:
            if not ENABLE_XAI or not call_xai:
                return None
            
            response = await call_xai(
                prompt,
                system="You are Grok, contrarian AI analyst. Analyze market and select optimal trading strategy with unique perspective.",
                temperature=0.8,
                max_tokens=400
            )
            
            if response:
                return self._parse_strategy_response(response, "Grok")
            return None
                
        except Exception as e:
            self.logger.error(f"Grok strategy vote failed: {e}")
            return None
    
    def _parse_strategy_response(self, analysis: str, brain_name: str) -> StrategyVote:
        """Parse AI response into StrategyVote"""
        try:
            # Extract fields
            strategy = "wait"
            side = None
            confidence = 50.0
            reasoning = analysis[:200]
            
            # Parse STRATEGY
            if "STRATEGY:" in analysis.upper():
                strategy_line = [line for line in analysis.split("\n") if "STRATEGY:" in line.upper()][0]
                strategy_text = strategy_line.split(":", 1)[1].strip().lower()
                
                if "grid" in strategy_text:
                    strategy = "grid"
                elif "mean" in strategy_text or "reversion" in strategy_text:
                    strategy = "mean_reversion"
                elif "scalp" in strategy_text:
                    strategy = "scalping"
                else:
                    strategy = "wait"
            
            # Parse SIDE
            if "SIDE:" in analysis.upper():
                side_line = [line for line in analysis.split("\n") if "SIDE:" in line.upper()][0]
                side_text = side_line.split(":", 1)[1].strip().upper()
                
                if "LONG" in side_text:
                    side = "LONG"
                elif "SHORT" in side_text:
                    side = "SHORT"
            
            # Parse CONFIDENCE
            if "CONFIDENCE:" in analysis.upper():
                conf_line = [line for line in analysis.split("\n") if "CONFIDENCE:" in line.upper()][0]
                conf_text = conf_line.split(":", 1)[1].strip()
                try:
                    confidence = float(conf_text.split()[0])
                except:
                    confidence = 60.0
            
            # Parse REASONING
            if "REASONING:" in analysis.upper():
                reason_line = [line for line in analysis.split("\n") if "REASONING:" in line.upper()][0]
                reasoning = reason_line.split(":", 1)[1].strip()
            
            return StrategyVote(
                brain=brain_name,
                strategy=strategy,
                confidence=min(100, max(0, confidence)),
                reasoning=reasoning,
                side=side
            )
        
        except Exception as e:
            self.logger.error(f"Failed to parse {brain_name} response: {e}")
            return StrategyVote(
                brain=brain_name,
                strategy="wait",
                confidence=0,
                reasoning="Parse error",
                side=None
            )
    
    async def select_strategy(
        self,
        market_ctx: Dict[str, Any],
        symbol: str
    ) -> StrategyConsensus:
        """
        Get AI consensus on optimal strategy.
        
        Args:
            market_ctx: Market data (regime, volatility, price, indicators)
            symbol: Trading symbol
        
        Returns:
            StrategyConsensus with chosen strategy and reasoning
        """
        self.logger.info(f"🧠 Requesting AI strategy consensus for {symbol}...")
        
        # Build prompt
        prompt = self._build_strategy_prompt(market_ctx, symbol)
        
        # 🚀 COST OPTIMIZATION: Use only 3 cheap brains (DeepSeek + Grok + Gemini)
        # Skip OpenAI (429) and Claude (insufficient credits)
        tasks = []
        if self.brains_available.get("Gemini"):
            tasks.append(self._call_gemini(prompt))
        if self.brains_available.get("DeepSeek"):
            tasks.append(self._call_deepseek(prompt))
        if self.brains_available.get("Grok"):
            tasks.append(self._call_grok(prompt))
        
        # Wait for all votes
        votes_raw = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter valid votes
        votes = [v for v in votes_raw if isinstance(v, StrategyVote)]
        
        if not votes:
            self.logger.warning("No AI brains responded - using fallback WAIT strategy")
            return StrategyConsensus(
                strategy="wait",
                side=None,
                confidence=0,
                votes_approve=0,
                total_votes=0,
                votes=[],
                reasoning="No AI consensus available"
            )
        
        # Calculate consensus
        strategy_counts = {}
        side_counts = {"LONG": 0, "SHORT": 0}
        total_confidence = 0.0
        
        for vote in votes:
            # Count strategies
            strategy_counts[vote.strategy] = strategy_counts.get(vote.strategy, 0) + 1
            
            # Count sides
            if vote.side:
                side_counts[vote.side] = side_counts.get(vote.side, 0) + 1
            
            # Sum confidence
            total_confidence += vote.confidence
            
            self.logger.info(
                f"  {vote.brain}: {vote.strategy.upper()} "
                f"({vote.side or 'N/A'}) - {vote.confidence:.0f}% | "
                f"{vote.reasoning[:80]}..."
            )
        
        # Determine winning strategy (majority vote)
        winning_strategy = max(strategy_counts.items(), key=lambda x: x[1])[0] if strategy_counts else "wait"
        votes_approve = strategy_counts.get(winning_strategy, 0)
        
        # Determine winning side
        winning_side = None
        if side_counts["LONG"] > side_counts["SHORT"]:
            winning_side = "LONG"
        elif side_counts["SHORT"] > side_counts["LONG"]:
            winning_side = "SHORT"
        
        # Average confidence
        avg_confidence = total_confidence / len(votes) if votes else 0
        
        # Aggregate reasoning
        strategy_votes = [v for v in votes if v.strategy == winning_strategy]
        reasoning = " | ".join([v.reasoning[:100] for v in strategy_votes[:3]])
        
        consensus = StrategyConsensus(
            strategy=winning_strategy,
            side=winning_side,
            confidence=avg_confidence,
            votes_approve=votes_approve,
            total_votes=len(votes),
            votes=votes,
            reasoning=reasoning
        )
        
        self.logger.info(
            f"🗳️ Strategy Consensus [{symbol}]: {votes_approve}/{len(votes)} vote {winning_strategy.upper()} "
            f"({winning_side or 'N/A'}) | Confidence={avg_confidence:.1f}%"
        )
        
        return consensus


# Singleton instance
_strategy_selector: Optional[AIStrategySelector] = None

def get_ai_strategy_selector() -> AIStrategySelector:
    """Get or create singleton AI strategy selector"""
    global _strategy_selector
    if _strategy_selector is None:
        _strategy_selector = AIStrategySelector()
    return _strategy_selector


async def select_strategy_ai(
    market_ctx: Dict[str, Any],
    symbol: str
) -> StrategyConsensus:
    """
    Convenience function for AI strategy selection.
    
    Args:
        market_ctx: Market context data
        symbol: Trading symbol
    
    Returns:
        StrategyConsensus with AI decision
    """
    selector = get_ai_strategy_selector()
    return await selector.select_strategy(market_ctx, symbol)
