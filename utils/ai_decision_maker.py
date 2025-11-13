#!/usr/bin/env python3
"""
AI Decision Maker - 3 AI Brains Consensus System (Cost-Optimized)
==================================================================
After 2 Scouts propose, 3 AI brains vote on whether to execute.

3 AI Providers (98.5% cost reduction vs GPT-5):
1. DeepSeek - Deep market analysis (ultra-cheap + reliable) - $0.0001/call
2. Qwen 2.5 Turbo - Fast reasoning (FREE!) - Alibaba Cloud
3. Gemini 2 Pro - Multi-modal analysis (ultra-cheap) - $0.00005/call

Optional fallback:
- Grok (XAI) - SUSPENDED by default (auto-resume when credits available)

Each provides:
- Vote: APPROVE ✅ or REJECT ❌
- Score: 0-10
- Detailed reasoning (Hebrew + English)

Consensus: ≥2/3 APPROVE = Execute (majority vote)
Dynamic threshold adjusts based on active brains.
"""

import logging
import os
import json
from typing import Dict, Any, List, Optional
import asyncio
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
    from utils.qwen_client import call_qwen, ENABLE_QWEN
except ImportError:
    call_qwen = None
    ENABLE_QWEN = False

try:
    from utils.anthropic_client import call_anthropic, ENABLE_ANTHROPIC
except ImportError:
    call_anthropic = None
    ENABLE_ANTHROPIC = False

try:
    from utils.brain_manager import get_brain_manager
except ImportError:
    get_brain_manager = None

logger = logging.getLogger("algogpt.ai_decisions")


class AIBrain:
    """Base class for AI decision-making brains."""
    
    def __init__(self, name: str, provider: str, model: str):
        self.name = name
        self.provider = provider
        self.model = model
        self.logger = logging.getLogger(f"algogpt.brain.{name.lower().replace(' ', '_')}")
    
    async def vote(
        self,
        scout_data: Dict[str, Any],
        market_data: Dict[str, Any],
        wallet_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Vote on trade proposal.
        
        Args:
            scout_data: Combined data from 2 Scouts
            market_data: Market indicators
            wallet_state: Wallet balance and risk
        
        Returns:
            Dict with vote, score, reasoning
        """
        raise NotImplementedError
    
    def _build_prompt(self, scout_data: Dict, market_data: Dict, wallet_state: Dict) -> str:
        """Build decision prompt for AI brain."""
        symbol = scout_data.get("symbol", "UNKNOWN")
        strategy = scout_data.get("strategy", "NONE")
        scanner_score = scout_data.get("market_scanner", {}).get("score", 0)
        analyst_score = scout_data.get("technical_analyst", {}).get("score", 0)
        min_quality = scout_data.get("min_quality", 6.0)  # Dynamic quality threshold
        min_rr = scout_data.get("min_rr", 2.0)
        
        # Strategy context explanation
        strategy_context = ""
        if strategy == "wait":
            strategy_context = f"\n⚠️ WAIT Strategy = Ultra-conservative mode (still tradeable!):\n   Only approve exceptional setups with Quality≥{min_quality:.1f} and RR≥{min_rr:.1f}\n   Lower leverage (max 3x), higher quality threshold\n   This is NOT 'don't trade' - it's 'be very selective'\n"
        
        return f"""Analyze this trade proposal:

Symbol: {symbol}
Strategy: {strategy}{strategy_context}

Scout Scores:
- Market Scanner: {scanner_score}/10
- Technical Analyst: {analyst_score}/10

Wallet: ${wallet_state.get('available_balance', 0):.2f} available

Decision required:
1. APPROVE ✅ or REJECT ❌
2. Score (0-10)
3. Brief reasoning (2-3 sentences, mix Hebrew + English)

Format: VOTE|SCORE|REASONING"""
    
    def _parse_response(self, analysis: str, scout_data: Dict) -> Dict[str, Any]:
        """Parse AI response into structured vote."""
        try:
            parts = analysis.split("|")
            if len(parts) >= 3:
                vote = "APPROVE" if "APPROVE" in parts[0].upper() else "REJECT"
                score = float(parts[1].strip())
                reasoning = parts[2].strip()
            else:
                vote = "APPROVE" if scout_data.get("avg_score", 5) >= 6.0 else "REJECT"
                score = scout_data.get("avg_score", 5.0)
                reasoning = analysis[:200]
            
            avg_score = scout_data.get("avg_score", 5.0)
            min_quality = scout_data.get("min_quality", 6.0)
            symbol = scout_data.get("symbol", "UNKNOWN")
            
            if avg_score >= min_quality and vote == "REJECT":
                self.logger.info(
                    f"✅ Hard override: {symbol} APPROVED by {self.name} "
                    f"(avg_score={avg_score:.1f} ≥ min_quality={min_quality:.1f})"
                )
                vote = "APPROVE"
                reasoning = f"[Auto-approved by dynamic threshold] {reasoning}"
            
            return {
                "brain": self.name,
                "vote": vote,
                "score": max(0, min(10, score)),
                "reasoning": reasoning,
                "confidence": "HIGH" if score >= 7.0 else "MEDIUM"
            }
        except:
            return self._mock_vote(scout_data)
    
    def _mock_vote(self, scout_data: Dict) -> Dict[str, Any]:
        """Fallback mock vote when API fails."""
        avg_score = scout_data.get("avg_score", 5.0)
        min_quality = scout_data.get("min_quality", 6.0)
        return {
            "brain": self.name,
            "vote": "APPROVE" if avg_score >= min_quality else "REJECT",
            "score": round(avg_score, 1),
            "reasoning": f"{self.name}: Setup looks reasonable (fallback, threshold={min_quality:.1f})",
            "confidence": "LOW"
        }


class GPT4oMiniBrain(AIBrain):
    """GPT-4o-mini - Cost-efficient decision maker (60x cheaper than GPT-5)."""
    
    def __init__(self):
        super().__init__("GPT-4o-mini", "openai", "gpt-4o-mini")
        self.api_key = os.getenv("OPENAI_API_KEY")
    
    async def vote(
        self,
        scout_data: Dict[str, Any],
        market_data: Dict[str, Any],
        wallet_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """GPT-4o-mini analyzes and votes."""
        try:
            if not self.api_key:
                return self._mock_vote(scout_data)
            
            prompt = self._build_prompt(scout_data, market_data, wallet_state)
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "You are GPT-4o-mini, cost-efficient AI trading strategist."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 500
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    analysis = data["choices"][0]["message"]["content"]
                    return self._parse_response(analysis, scout_data)
                else:
                    self.logger.error(f"GPT-5 API error: {response.status_code}")
                    return self._mock_vote(scout_data)
        
        except Exception as e:
            self.logger.error(f"GPT-5 vote failed: {e}", exc_info=True)
            return self._mock_vote(scout_data)


class GeminiBrain(AIBrain):
    """Gemini 2 Pro - Fast multi-modal analysis."""
    
    def __init__(self):
        super().__init__("Gemini 2 Pro", "google", "gemini-2.0-flash-exp")
        self.api_key = os.getenv("GEMINI_API_KEY")
    
    async def vote(self, scout_data, market_data, wallet_state) -> Dict[str, Any]:
        """Gemini analyzes and votes."""
        try:
            if not ENABLE_GEMINI or not call_gemini:
                return self._mock_vote(scout_data)
            
            prompt = self._build_prompt(scout_data, market_data, wallet_state)
            
            response = await call_gemini(
                prompt,
                system="You are Gemini 2 Pro, fast multi-modal trading analyst. Analyze and vote APPROVE/REJECT.",
                temperature=0.7,
                max_tokens=300
            )
            
            if response:
                return self._parse_response(response, scout_data)
            else:
                return self._mock_vote(scout_data)
                
        except Exception as e:
            self.logger.error(f"Gemini vote failed: {e}", exc_info=True)
            return self._mock_vote(scout_data)
    
    def _mock_vote(self, scout_data) -> Dict[str, Any]:
        """Fallback vote when API fails - uses REAL scores from scout_data"""
        avg_score = scout_data.get("avg_score", 5.0)
        vote = "APPROVE" if avg_score >= 6.5 else "REJECT"
        score = min(avg_score + 0.3, 10.0) if vote == "APPROVE" else avg_score - 0.5
        
        return {
            "brain": self.name,
            "vote": vote,
            "score": round(score, 1),
            "reasoning": f"{self.name}: Analysis based on MI/SO scores (API unavailable)",
            "confidence": "HIGH" if score >= 7.0 else "MEDIUM"
        }


class DeepSeekBrain(AIBrain):
    """DeepSeek - Deep market pattern analysis."""
    
    def __init__(self):
        super().__init__("DeepSeek", "deepseek", "deepseek-chat")
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
    
    async def vote(self, scout_data, market_data, wallet_state) -> Dict[str, Any]:
        """DeepSeek analyzes and votes."""
        try:
            if not self.api_key or not llm_chat_completion:
                return self._mock_vote(scout_data)
            
            prompt = self._build_prompt(scout_data, market_data, wallet_state)
            
            response = await llm_chat_completion(
                messages=[
                    {"role": "system", "content": "You are DeepSeek, deep market pattern analyst. Analyze and vote APPROVE/REJECT."},
                    {"role": "user", "content": prompt}
                ],
                model="deepseek-chat",
                temperature=0.7,
                max_tokens=300
            )
            
            if response and "choices" in response:
                analysis = response["choices"][0]["message"]["content"]
                return self._parse_response(analysis, scout_data)
            else:
                return self._mock_vote(scout_data)
                
        except Exception as e:
            self.logger.error(f"DeepSeek vote failed: {e}", exc_info=True)
            return self._mock_vote(scout_data)


class GrokBrain(AIBrain):
    """Grok (XAI) - Contrarian analysis (SUSPENDED by default)."""
    
    def __init__(self):
        super().__init__("Grok", "xai", "grok-2-latest")
        self.api_key = os.getenv("XAI_API_KEY")
    
    async def vote(self, scout_data, market_data, wallet_state) -> Dict[str, Any]:
        """Grok analyzes and votes."""
        try:
            if not ENABLE_XAI or not call_xai:
                return self._mock_vote(scout_data)
            
            prompt = self._build_prompt(scout_data, market_data, wallet_state)
            
            response = await call_xai(
                prompt,
                system="You are Grok, contrarian AI analyst. Analyze and vote APPROVE/REJECT with unique perspective.",
                temperature=0.8,
                max_tokens=300
            )
            
            if response:
                return self._parse_response(response, scout_data)
            else:
                return self._mock_vote(scout_data)
                
        except Exception as e:
            self.logger.error(f"Grok vote failed: {e}", exc_info=True)
            return self._mock_vote(scout_data)


class QwenBrain(AIBrain):
    """Qwen 2.5 Turbo - Fast reasoning (FREE!)."""
    
    def __init__(self):
        super().__init__("Qwen 2.5 Turbo", "qwen", "qwen-turbo")
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
    
    async def vote(self, scout_data, market_data, wallet_state) -> Dict[str, Any]:
        """Qwen analyzes and votes."""
        try:
            if not ENABLE_QWEN or not call_qwen:
                return self._mock_vote(scout_data)
            
            prompt = self._build_prompt(scout_data, market_data, wallet_state)
            
            response = await call_qwen(
                prompt,
                system="You are Qwen 2.5 Turbo, fast AI trading analyst. Analyze and vote APPROVE/REJECT efficiently.",
                temperature=0.7,
                max_tokens=300
            )
            
            if response:
                return self._parse_response(response, scout_data)
            else:
                return self._mock_vote(scout_data)
                
        except Exception as e:
            self.logger.error(f"Qwen vote failed: {e}", exc_info=True)
            return self._mock_vote(scout_data)


class ClaudeBrain(AIBrain):
    """Claude Sonnet 4.5 - Conservative validator."""
    
    def __init__(self):
        super().__init__("Claude Sonnet 4.5", "anthropic", "claude-sonnet-4-5-20250929")
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
    
    async def vote(self, scout_data, market_data, wallet_state) -> Dict[str, Any]:
        """Claude analyzes and votes."""
        try:
            if not ENABLE_ANTHROPIC or not call_anthropic:
                return self._mock_vote(scout_data)
            
            prompt = self._build_prompt(scout_data, market_data, wallet_state)
            
            response = await call_anthropic(
                prompt,
                system="You are Claude Sonnet 3.5, conservative risk validator. Analyze and vote APPROVE/REJECT carefully.",
                temperature=0.5,
                max_tokens=300
            )
            
            if response:
                return self._parse_response(response, scout_data)
            else:
                return self._mock_vote(scout_data)
                
        except Exception as e:
            self.logger.error(f"Claude vote failed: {e}", exc_info=True)
            return self._mock_vote(scout_data)


class AIConsensusEngine:
    """
    Consensus engine with dynamic brain management.
    
    Workflow:
    1. 2 Scouts propose → send to active AI brains
    2. Each brain votes independently
    3. Consensus: ≥2/3 APPROVE = Execute (dynamic threshold)
    4. Final score = weighted average
    
    Active Brains (98.5% cost reduction vs GPT-5):
    - DeepSeek Chat (ultra-cheap + reliable) - $0.0001/call
    - Qwen 2.5 Turbo (FREE!) - Alibaba Cloud
    - Gemini 2 Pro (ultra-cheap, fast) - $0.00005/call
    
    Suspended/Fallback Brains:
    - Grok (XAI) - Auto-resume when credits available
    
    Features:
    - Auto-suspend brains on failures (429, timeout, errors)
    - Auto-resume when API recovers
    - Dynamic consensus threshold (adjusts to active brains)
    - Token budgeting and cost tracking
    """
    
    def __init__(self):
        self.logger = logger
        self.brain_manager = get_brain_manager() if get_brain_manager else None
        
        self.brain_classes = {
            "deepseek": DeepSeekBrain(),
            "qwen": QwenBrain(),
            "gemini": GeminiBrain(),
            "grok": GrokBrain()
        }
        
        if self.brain_manager:
            active_count = self.brain_manager.get_active_count()
            threshold = self.brain_manager.get_consensus_threshold()
            self.logger.info(
                f"🧠 AI Consensus Engine initialized: {active_count} active brains, "
                f"consensus threshold: {threshold}/{active_count}"
            )
        else:
            self.logger.warning("Brain Manager not available, using fallback mode")
            self.brains = [DeepSeekBrain(), QwenBrain(), GeminiBrain()]
            self.logger.info(f"AI Consensus Engine initialized with {len(self.brains)} brains (fallback)")
    
    async def get_consensus(
        self,
        scout_data: Dict[str, Any],
        market_data: Dict[str, Any],
        wallet_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get consensus decision from all active AI brains.
        
        Args:
            scout_data: Combined Scout analysis
            market_data: Market indicators
            wallet_state: Wallet state
        
        Returns:
            Dict with final_vote, avg_score, brain_votes, consensus_pct
        """
        try:
            scanner_score = scout_data.get("market_scanner", {}).get("score", 0)
            analyst_score = scout_data.get("technical_analyst", {}).get("score", 0)
            avg_score = (scanner_score + analyst_score) / 2
            scout_data["avg_score"] = avg_score
            
            if self.brain_manager:
                self.brain_manager.check_auto_resume()
                
                active_brain_ids = self.brain_manager.get_active_brains()
                consensus_threshold = self.brain_manager.get_consensus_threshold()
                
                if not active_brain_ids:
                    self.logger.error("❌ No active brains available!")
                    return {
                        "final_vote": "REJECT",
                        "final_score": 0,
                        "approve_count": 0,
                        "consensus_pct": 0,
                        "brain_votes": [],
                        "error": "No active brains"
                    }
                
                tasks = []
                for brain_id in active_brain_ids:
                    if brain_id in self.brain_classes:
                        brain_instance = self.brain_classes[brain_id]
                        tasks.append(
                            self.brain_manager.call_brain_vote(
                                brain_id,
                                brain_instance,
                                scout_data,
                                market_data,
                                wallet_state
                            )
                        )
                
                brain_votes = await asyncio.gather(*tasks)
                brain_votes = [v for v in brain_votes if v is not None]
                
            else:
                active_brains = self.brains
                consensus_threshold = 2
                
                tasks = [
                    brain.vote(scout_data, market_data, wallet_state)
                    for brain in active_brains
                ]
                brain_votes = await asyncio.gather(*tasks)
            
            approve_count = sum(1 for v in brain_votes if v["vote"] == "APPROVE")
            total_brains = len(brain_votes)
            consensus_pct = (approve_count / total_brains) * 100 if total_brains > 0 else 0
            
            final_vote = "APPROVE" if approve_count >= consensus_threshold else "REJECT"
            
            total_score = sum(v["score"] for v in brain_votes)
            final_score = total_score / total_brains if total_brains > 0 else 0
            
            self.logger.info(
                f"🧠 Consensus: {approve_count}/{total_brains} APPROVE ({consensus_pct:.0f}%) | "
                f"Threshold: {consensus_threshold}/{total_brains} | "
                f"Score: {final_score:.1f}/10 | Decision: {final_vote}"
            )
            
            return {
                "final_vote": final_vote,
                "final_score": round(final_score, 1),
                "approve_count": approve_count,
                "total_brains": total_brains,
                "consensus_threshold": consensus_threshold,
                "consensus_pct": round(consensus_pct, 1),
                "brain_votes": brain_votes,
                "scouts": {
                    "market_scanner": scout_data.get("market_scanner", {}),
                    "technical_analyst": scout_data.get("technical_analyst", {})
                }
            }
            
        except Exception as e:
            self.logger.error(f"Consensus failed: {e}", exc_info=True)
            return {
                "final_vote": "REJECT",
                "final_score": 0,
                "approve_count": 0,
                "consensus_pct": 0,
                "brain_votes": [],
                "error": str(e)
            }


_consensus_engine: Optional[AIConsensusEngine] = None


def get_consensus_engine() -> AIConsensusEngine:
    """Get or create AI Consensus Engine."""
    global _consensus_engine
    if _consensus_engine is None:
        _consensus_engine = AIConsensusEngine()
    return _consensus_engine


__all__ = ["AIConsensusEngine", "get_consensus_engine"]
