#!/usr/bin/env python3
# utils/ai_trade_scorer.py
"""
Multi-AI Trade Scorer - Consensus-based trade scoring with 3 AI providers
Supports OpenAI (GPT-5), DeepSeek, and AI-X (Grok) with budget tracking and fallbacks
Includes dynamic weighting based on historical AI performance
"""
import os
import logging
import asyncio
from typing import Dict, Any, List, Optional, Literal
from dataclasses import dataclass
import httpx

logger = logging.getLogger("algogpt.ai_trade_scorer")

# Import AI performance tracker for dynamic weighting
try:
    from utils.ai_tracker import get_dynamic_weights, MarketRegime
    AI_TRACKER_AVAILABLE = True
except ImportError:
    logger.warning("AI tracker not available, using static weights")
    AI_TRACKER_AVAILABLE = False

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()

# Models
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-2025-08-07")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-beta")

# API Endpoints
OPENAI_BASE_URL = "https://api.openai.com/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
XAI_BASE_URL = "https://api.x.ai/v1"

# Budget tracking (in USD)
OPENAI_BUDGET = float(os.getenv("OPENAI_BUDGET", "40.0"))
DEEPSEEK_BUDGET = float(os.getenv("DEEPSEEK_BUDGET", "10.0"))
XAI_BUDGET = float(os.getenv("XAI_BUDGET", "-15.0"))  # Can have credit/debit

# Feature flags
ENABLE_MULTI_AI_CONSENSUS = os.getenv("ENABLE_MULTI_AI_CONSENSUS", "1").lower() in ("1", "true", "yes")
CONSENSUS_MIN_PROVIDERS = int(os.getenv("CONSENSUS_MIN_PROVIDERS", "2"))
ENABLE_OPENAI = os.getenv("ENABLE_OPENAI", "1").lower() in ("1", "true", "yes") and bool(OPENAI_API_KEY)
ENABLE_DEEPSEEK = os.getenv("ENABLE_DEEPSEEK", "1").lower() in ("1", "true", "yes") and bool(DEEPSEEK_API_KEY)
ENABLE_XAI = os.getenv("ENABLE_XAI", "1").lower() in ("1", "true", "yes") and bool(XAI_API_KEY)

AIProvider = Literal["openai", "deepseek", "xai"]

@dataclass
class AIResponse:
    """Response from an AI provider"""
    provider: AIProvider
    score: float  # 0-100
    confidence: float  # 0-100
    reasoning: str
    success: bool
    error: Optional[str] = None


class MultiAIScorer:
    """
    Multi-AI consensus-based trade scorer
    Uses multiple AI providers to score trade proposals and achieve consensus
    """
    
    def __init__(self):
        self.providers_enabled = {
            "openai": ENABLE_OPENAI,
            "deepseek": ENABLE_DEEPSEEK,
            "xai": ENABLE_XAI
        }
        self.budgets = {
            "openai": OPENAI_BUDGET,
            "deepseek": DEEPSEEK_BUDGET,
            "xai": XAI_BUDGET
        }
        self.usage_tracking: Dict[AIProvider, float] = {
            "openai": 0.0,
            "deepseek": 0.0,
            "xai": 0.0
        }
        logger.info(f"Multi-AI Scorer initialized: OpenAI={ENABLE_OPENAI}, DeepSeek={ENABLE_DEEPSEEK}, XAI={ENABLE_XAI}")
    
    async def _call_openai(self, prompt: str, max_tokens: int = 500) -> AIResponse:
        """Call OpenAI GPT-5 API"""
        if not ENABLE_OPENAI:
            return AIResponse("openai", 0, 0, "", False, "OpenAI disabled")
        
        try:
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are an expert trading analyst. Provide numerical scores 0-100."},
                    {"role": "user", "content": prompt}
                ],
                "max_completion_tokens": max_tokens
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{OPENAI_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                # Parse score and confidence from response
                score, confidence, reasoning = self._parse_ai_response(content)
                
                # Track usage (rough estimate: $0.01 per 1K tokens)
                tokens = data.get("usage", {}).get("total_tokens", 1000)
                cost = (tokens / 1000) * 0.01
                self.usage_tracking["openai"] += cost
                
                return AIResponse("openai", score, confidence, reasoning, True)
        
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return AIResponse("openai", 0, 0, "", False, str(e))
    
    async def _call_deepseek(self, prompt: str, max_tokens: int = 500) -> AIResponse:
        """Call DeepSeek API"""
        if not ENABLE_DEEPSEEK:
            return AIResponse("deepseek", 0, 0, "", False, "DeepSeek disabled")
        
        try:
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": "You are an expert trading analyst. Provide numerical scores 0-100."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{DEEPSEEK_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                score, confidence, reasoning = self._parse_ai_response(content)
                
                # Track usage (estimate: $0.001 per 1K tokens)
                tokens = data.get("usage", {}).get("total_tokens", 1000)
                cost = (tokens / 1000) * 0.001
                self.usage_tracking["deepseek"] += cost
                
                return AIResponse("deepseek", score, confidence, reasoning, True)
        
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            return AIResponse("deepseek", 0, 0, "", False, str(e))
    
    async def _call_xai(self, prompt: str, max_tokens: int = 500) -> AIResponse:
        """Call AI-X (Grok) API"""
        if not ENABLE_XAI:
            return AIResponse("xai", 0, 0, "", False, "XAI disabled")
        
        try:
            headers = {
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": XAI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are an expert trading analyst. Provide numerical scores 0-100."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": max_tokens
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{XAI_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                score, confidence, reasoning = self._parse_ai_response(content)
                
                # Track usage (estimate: $0.005 per 1K tokens)
                tokens = data.get("usage", {}).get("total_tokens", 1000)
                cost = (tokens / 1000) * 0.005
                self.usage_tracking["xai"] += cost
                
                return AIResponse("xai", score, confidence, reasoning, True)
        
        except Exception as e:
            logger.error(f"XAI API error: {e}")
            return AIResponse("xai", 0, 0, "", False, str(e))
    
    def _parse_ai_response(self, content: str) -> tuple[float, float, str]:
        """Parse score, confidence, and reasoning from AI response"""
        try:
            lines = content.strip().split("\n")
            score = 70.0
            confidence = 70.0
            reasoning = content[:200]
            
            for line in lines:
                lower_line = line.lower()
                if "score:" in lower_line or "trade score:" in lower_line:
                    try:
                        score = float(''.join(filter(str.isdigit, line.split(":")[-1][:5])))
                    except:
                        pass
                if "confidence:" in lower_line:
                    try:
                        confidence = float(''.join(filter(str.isdigit, line.split(":")[-1][:5])))
                    except:
                        pass
            
            return min(max(score, 0), 100), min(max(confidence, 0), 100), reasoning
        
        except Exception as e:
            logger.warning(f"Failed to parse AI response: {e}")
            return 70.0, 70.0, content[:200]
    
    async def score_trade_consensus(
        self,
        trade_data: Dict[str, Any],
        use_providers: Optional[List[AIProvider]] = None
    ) -> Dict[str, Any]:
        """
        Score trade using multi-AI consensus
        
        Args:
            trade_data: Trade proposal data (symbol, side, entry, sl, tp, etc.)
            use_providers: Optional list of specific providers to use
        
        Returns:
            {
                "consensus_score": float,  # 0-100
                "consensus_confidence": float,  # 0-100
                "providers_used": List[str],
                "individual_responses": List[AIResponse],
                "recommendation": str  # "STRONG_BUY", "BUY", "NEUTRAL", "AVOID"
            }
        """
        if not ENABLE_MULTI_AI_CONSENSUS:
            logger.info("Multi-AI consensus disabled, using fallback")
            return {
                "consensus_score": 70.0,
                "consensus_confidence": 50.0,
                "providers_used": [],
                "individual_responses": [],
                "recommendation": "NEUTRAL"
            }
        
        # Build prompt
        prompt = self._build_trade_prompt(trade_data)
        
        # Determine which providers to use
        if use_providers is None:
            use_providers = [p for p, enabled in self.providers_enabled.items() if enabled]  # type: ignore
        
        logger.info(f"Scoring trade with providers: {use_providers}")
        
        # Call all enabled providers in parallel
        tasks = []
        if use_providers and "openai" in use_providers and ENABLE_OPENAI:
            tasks.append(self._call_openai(prompt))
        if use_providers and "deepseek" in use_providers and ENABLE_DEEPSEEK:
            tasks.append(self._call_deepseek(prompt))
        if use_providers and "xai" in use_providers and ENABLE_XAI:
            tasks.append(self._call_xai(prompt))
        
        responses: List[AIResponse] = await asyncio.gather(*tasks) if tasks else []
        
        # Filter successful responses
        successful = [r for r in responses if r.success]
        
        if len(successful) < CONSENSUS_MIN_PROVIDERS:
            logger.warning(f"Only {len(successful)} providers responded, minimum is {CONSENSUS_MIN_PROVIDERS}")
            # Fallback to single provider if available
            if successful:
                return {
                    "consensus_score": successful[0].score,
                    "consensus_confidence": successful[0].confidence * 0.5,  # Reduce confidence
                    "providers_used": [successful[0].provider],
                    "individual_responses": successful,
                    "recommendation": self._get_recommendation(successful[0].score),
                    "weights_used": {},  # No weights for single provider
                }
            else:
                return {
                    "consensus_score": 50.0,
                    "consensus_confidence": 0.0,
                    "providers_used": [],
                    "individual_responses": responses,
                    "recommendation": "AVOID",
                    "weights_used": {},
                }
        
        # 📊 DYNAMIC WEIGHTING: Get performance-based weights
        # Extract market regime from trade_data if available
        regime_str = trade_data.get("regime", "UNKNOWN")
        if regime_str not in ("TRENDING", "RANGING", "VOLATILE", "UNKNOWN"):
            regime_str = "UNKNOWN"
        
        # Get dynamic weights based on historical performance
        if AI_TRACKER_AVAILABLE:
            try:
                dynamic_weights = get_dynamic_weights(regime=regime_str, timeframe_days=7)  # type: ignore
                # Map provider names to model names
                provider_to_model = {
                    "openai": "gpt5",
                    "deepseek": "deepseek",
                    "xai": "grok"
                }
                weights_dict = {}
                for r in successful:
                    model_name = provider_to_model.get(r.provider, "gpt5")
                    weights_dict[r.provider] = dynamic_weights.get(model_name, 1.0)
                
                logger.info(f"🎯 Dynamic weights for {regime_str}: {weights_dict}")
            except Exception as e:
                logger.warning(f"Failed to get dynamic weights, using static: {e}")
                # Fallback to static weights
                weights_dict = {r.provider: 1.0 for r in successful}
        else:
            # Static weights fallback
            weights_dict = {
                "openai": 0.50,
                "deepseek": 0.30,
                "xai": 0.20
            }
            # Only use weights for providers that responded
            weights_dict = {k: v for k, v in weights_dict.items() if any(r.provider == k for r in successful)}
        
        # Calculate consensus score using dynamic weights
        total_weight = sum(weights_dict.get(r.provider, 1.0) * r.confidence for r in successful)
        if total_weight > 0:
            consensus_score = sum(
                r.score * r.confidence * weights_dict.get(r.provider, 1.0)
                for r in successful
            ) / total_weight
        else:
            consensus_score = sum(r.score for r in successful) / len(successful)
        
        # Calculate consensus confidence (weighted average)
        total_conf_weight = sum(weights_dict.get(r.provider, 1.0) for r in successful)
        if total_conf_weight > 0:
            consensus_confidence = sum(
                r.confidence * weights_dict.get(r.provider, 1.0)
                for r in successful
            ) / total_conf_weight
        else:
            consensus_confidence = sum(r.confidence for r in successful) / len(successful)
        
        # Boost confidence if multiple providers agree
        if len(successful) >= 3:
            consensus_confidence = min(consensus_confidence * 1.2, 100.0)
        
        recommendation = self._get_recommendation(consensus_score)
        
        # 📋 AUDIT LOGGING: Log weights used in this decision
        logger.info(
            f"Consensus: score={consensus_score:.1f}, confidence={consensus_confidence:.1f}, "
            f"providers={len(successful)}, recommendation={recommendation}, "
            f"regime={regime_str}, weights={weights_dict}"
        )
        
        return {
            "consensus_score": consensus_score,
            "consensus_confidence": consensus_confidence,
            "providers_used": [r.provider for r in successful],
            "individual_responses": [
                {
                    "provider": r.provider,
                    "score": r.score,
                    "confidence": r.confidence,
                    "reasoning": r.reasoning[:100]
                }
                for r in successful
            ],
            "recommendation": recommendation,
            "budget_usage": self.usage_tracking.copy(),
            "weights_used": weights_dict,  # Audit trail for dynamic weights
            "market_regime": regime_str  # Track which regime weights were optimized for
        }
    
    def _build_trade_prompt(self, trade_data: Dict[str, Any]) -> str:
        """Build trade scoring prompt"""
        symbol = trade_data.get("symbol", "UNKNOWN")
        side = trade_data.get("side", "LONG")
        entry = trade_data.get("entry", 0)
        sl = trade_data.get("sl", 0)
        tp = trade_data.get("tp") or trade_data.get("tp1", 0)
        
        rr = ((tp - entry) / (entry - sl)) if sl < entry else 0
        
        prompt = f"""Analyze this crypto trade proposal and provide a score 0-100:

Symbol: {symbol}
Side: {side}
Entry: ${entry}
Stop Loss: ${sl}
Take Profit: ${tp}
Risk/Reward: {rr:.2f}

Additional context:
{trade_data.get('reason', 'No reason provided')}

Provide your response in this format:
Trade Score: [0-100]
Confidence: [0-100]
Reasoning: [2-3 sentences explaining your score]
"""
        return prompt
    
    def _get_recommendation(self, score: float) -> str:
        """Get recommendation based on consensus score"""
        if score >= 80:
            return "STRONG_BUY"
        elif score >= 65:
            return "BUY"
        elif score >= 45:
            return "NEUTRAL"
        else:
            return "AVOID"
    
    def get_budget_status(self) -> Dict[str, Any]:
        """Get current budget usage status"""
        return {
            "openai": {
                "budget": OPENAI_BUDGET,
                "used": self.usage_tracking["openai"],
                "remaining": OPENAI_BUDGET - self.usage_tracking["openai"],
                "enabled": ENABLE_OPENAI
            },
            "deepseek": {
                "budget": DEEPSEEK_BUDGET,
                "used": self.usage_tracking["deepseek"],
                "remaining": DEEPSEEK_BUDGET - self.usage_tracking["deepseek"],
                "enabled": ENABLE_DEEPSEEK
            },
            "xai": {
                "budget": XAI_BUDGET,
                "used": self.usage_tracking["xai"],
                "remaining": XAI_BUDGET - self.usage_tracking["xai"],
                "enabled": ENABLE_XAI
            }
        }


# Global instance
_scorer_instance: Optional[MultiAIScorer] = None

def get_multi_ai_scorer() -> MultiAIScorer:
    """Get or create global multi-AI scorer instance"""
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = MultiAIScorer()
    return _scorer_instance


# Convenience function for quick scoring
async def score_trade(trade_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to score a trade using multi-AI consensus"""
    scorer = get_multi_ai_scorer()
    return await scorer.score_trade_consensus(trade_data)


__all__ = ["MultiAIScorer", "get_multi_ai_scorer", "score_trade", "AIResponse"]
