#!/usr/bin/env python3
"""
MetaBrain v9.0 Orchestrator - Central Integration Layer
=========================================================
Connects 2 AI Scouts + 5 AI Brains + 3 System Modules.

Flow:
1. Market Scanner (Scout 1) scans symbol → proposes strategy + score
2. Technical Analyst (Scout 2) analyzes setup → calculates RR, SL/TP
3. Combined Scout data → sent to 5 AI Brains for consensus voting
4. 3+ APPROVE votes → trade approved
5. Budget Manager → calculates position size
6. Execute trade

All reports in 70% Hebrew, 30% English.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List
from decimal import Decimal

logger = logging.getLogger("algogpt.metabrain_orchestrator")


class MetaBrainOrchestrator:
    """
    Central orchestrator that coordinates:
    - 2 AI Scouts (Market Scanner + Technical Analyst)
    - 5 AI Brains (GPT-5, Gemini, DeepSeek, Grok, Claude)
    - 3 System Modules (Market Intelligence, Budget Manager, Strategy Orchestrator)
    """
    
    def __init__(self):
        self.logger = logger
        self.logger.info("🧠 MetaBrain v9.0 Orchestrator initialized")
        
        # Import components on-demand to avoid circular imports
        from utils.ai_scouts import get_market_scanner, get_technical_analyst
        from utils.ai_decision_maker import get_consensus_engine
        from utils.market_intelligence import get_market_intelligence
        from utils.dynamic_budget_manager import get_budget_manager
        from utils.strategy_orchestrator import get_strategy_orchestrator
        
        # 2 Scouts
        self.market_scanner = get_market_scanner()
        self.technical_analyst = get_technical_analyst()
        
        # 5 AI Brains
        self.consensus_engine = get_consensus_engine()
        
        # 3 System Modules
        self.market_intelligence = get_market_intelligence()
        self.budget_manager = get_budget_manager()
        self.strategy_orchestrator = get_strategy_orchestrator()
        
        self.logger.info("✅ All 10 modules loaded: 2 Scouts + 5 Brains + 3 Systems")
    
    async def analyze_and_propose(
        self,
        symbol: str,
        market_data: Dict[str, Any],
        wallet_state: Dict[str, Any],
        multi_tf_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Main workflow: 2 Scouts → 5 Brains → Final Decision.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            market_data: Price, volume, indicators
            wallet_state: Available balance, open positions
            multi_tf_data: Multi-timeframe analysis (optional)
        
        Returns:
            Dict with final_decision, trade_params, all_scores
        """
        try:
            self.logger.info(f"🔍 MetaBrain analyzing {symbol}...")
            
            # === PHASE 1: 2 SCOUTS ANALYZE ===
            self.logger.info(f"📊 Phase 1: 2 Scouts analyzing {symbol}")
            
            # Scout 1: Market Scanner
            scanner_result = self.market_scanner.scan_symbol(symbol, market_data)
            self.logger.info(
                f"🔍 Scout 1 (Market Scanner): {symbol} → "
                f"Score {scanner_result['score']}/10, Strategy: {scanner_result['strategy']}"
            )
            
            # Scout 2: Technical Analyst
            proposed_strategy = scanner_result['strategy']
            if proposed_strategy == "NONE":
                # If scanner didn't propose, check market intelligence
                mi_condition = self.market_intelligence.analyze_market(market_data)
                proposed_strategy = mi_condition.recommended_strategy or "LONG"
            
            analyst_result = self.technical_analyst.analyze_setup(
                symbol,
                proposed_strategy,
                market_data,
                multi_tf_data
            )
            self.logger.info(
                f"📈 Scout 2 (Technical Analyst): {symbol} → "
                f"Score {analyst_result['score']}/10, Quality: {analyst_result['entry_quality']}, "
                f"RR: {analyst_result.get('risk_reward', 0):.2f}:1"
            )
            
            # Combine Scout data
            scout_data = {
                "symbol": symbol,
                "strategy": analyst_result["strategy"],
                "market_scanner": scanner_result,
                "technical_analyst": analyst_result,
                "avg_score": (scanner_result["score"] + analyst_result["score"]) / 2,
                "sl_price": analyst_result.get("sl_price"),
                "tp_price": analyst_result.get("tp_price"),
                "risk_reward": analyst_result.get("risk_reward", 0)
            }
            
            # Check if Scouts recommend proceeding
            if scout_data["avg_score"] < 5.0:
                self.logger.info(
                    f"❌ {symbol}: Scouts score too low ({scout_data['avg_score']:.1f}/10) - REJECTED"
                )
                return {
                    "decision": "REJECT",
                    "reason": "Scout score below 5.0",
                    "scouts": scout_data,
                    "consensus": None
                }
            
            # === PHASE 2: 5 AI BRAINS CONSENSUS ===
            self.logger.info(f"🧠 Phase 2: 5 AI Brains voting on {symbol}")
            
            consensus_result = await self.consensus_engine.get_consensus(
                scout_data,
                market_data,
                wallet_state
            )
            
            approve_count = consensus_result["approve_count"]
            final_vote = consensus_result["final_vote"]
            final_score = consensus_result["final_score"]
            
            self.logger.info(
                f"🗳️ Consensus Result: {approve_count}/5 APPROVE "
                f"({consensus_result['consensus_pct']:.0f}%) | "
                f"Final Score: {final_score:.1f}/10 | Decision: {final_vote}"
            )
            
            # Log each brain's vote
            for brain_vote in consensus_result["brain_votes"]:
                vote_emoji = "✅" if brain_vote["vote"] == "APPROVE" else "❌"
                self.logger.info(
                    f"  {vote_emoji} {brain_vote['brain']}: {brain_vote['score']:.1f}/10 - {brain_vote['reasoning'][:60]}"
                )
            
            # === PHASE 3: FINAL DECISION ===
            if final_vote == "REJECT":
                self.logger.info(f"❌ {symbol}: Consensus REJECTED ({approve_count}/5 approve)")
                return {
                    "decision": "REJECT",
                    "reason": f"Only {approve_count}/5 brains approved",
                    "scouts": scout_data,
                    "consensus": consensus_result
                }
            
            # === PHASE 4: BUDGET & POSITION SIZING ===
            self.logger.info(f"💰 Phase 3: Budget Manager calculating position for {symbol}")
            
            # Budget Manager calculates position size
            budget_result = self.budget_manager.calculate_position_size(
                quality_score=final_score,
                rr_ratio=scout_data["risk_reward"],
                volatility_pct=market_data.get("atr_pct", 2.0),
                regime=market_data.get("regime", "CHOPPY")
            )
            
            self.logger.info(
                f"💰 Budget: ${budget_result['budget_usd']:.2f} | "
                f"Leverage: {budget_result['leverage']}x | "
                f"Position: ${budget_result['position_size_usd']:.2f}"
            )
            
            # === FINAL APPROVAL ===
            self.logger.info(f"✅ {symbol}: APPROVED - Preparing trade execution")
            
            return {
                "decision": "APPROVE",
                "symbol": symbol,
                "strategy": scout_data["strategy"],
                "side": "LONG" if "LONG" in scout_data["strategy"] else "SHORT",
                "entry_price": market_data.get("price", 0),
                "sl_price": scout_data["sl_price"],
                "tp_price": scout_data["tp_price"],
                "risk_reward": scout_data["risk_reward"],
                
                # Scores from all 10 modules
                "scores": {
                    "scouts": {
                        "market_scanner": scanner_result["score"],
                        "technical_analyst": analyst_result["score"],
                        "avg": scout_data["avg_score"]
                    },
                    "brains": {
                        brain["brain"]: brain["score"]
                        for brain in consensus_result["brain_votes"]
                    },
                    "final": final_score,
                    "consensus_pct": consensus_result["consensus_pct"]
                },
                
                # Budget & sizing
                "budget": budget_result,
                
                # Full details for Telegram
                "scouts_detail": scout_data,
                "consensus_detail": consensus_result,
                "reasoning": self._build_reasoning(scout_data, consensus_result)
            }
            
        except Exception as e:
            self.logger.error(f"MetaBrain orchestration failed for {symbol}: {e}", exc_info=True)
            return {
                "decision": "REJECT",
                "reason": f"Orchestration error: {e}",
                "scouts": None,
                "consensus": None
            }
    
    def _build_reasoning(self, scout_data: Dict, consensus: Dict) -> str:
        """Build combined reasoning from Scouts and Brains."""
        parts = []
        
        # Scouts reasoning
        scanner_reasoning = scout_data["market_scanner"].get("reasoning", "")
        analyst_reasoning = scout_data["technical_analyst"].get("reasoning", "")
        
        if scanner_reasoning:
            parts.append(f"🔍 Scanner: {scanner_reasoning}")
        if analyst_reasoning:
            parts.append(f"📈 Analyst: {analyst_reasoning}")
        
        # Top brain reasonings
        brain_votes = consensus.get("brain_votes", [])
        approved_brains = [b for b in brain_votes if b["vote"] == "APPROVE"]
        
        if approved_brains:
            parts.append("🧠 Brains:")
            for brain in approved_brains[:3]:  # Top 3
                parts.append(f"  • {brain['brain']}: {brain['reasoning'][:80]}")
        
        return "\n".join(parts)


# Global instance
_orchestrator: Optional[MetaBrainOrchestrator] = None


def get_metabrain_orchestrator() -> MetaBrainOrchestrator:
    """Get or create MetaBrain Orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MetaBrainOrchestrator()
    return _orchestrator


__all__ = ["MetaBrainOrchestrator", "get_metabrain_orchestrator"]
