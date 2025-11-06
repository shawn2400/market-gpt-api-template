#!/usr/bin/env python3
# utils/ai_consensus_improver.py
"""
AI Consensus Improver - Autonomous Parameter Optimization
=========================================================
Analyzes AI brain reviews and automatically applies improvements when
3+ brains agree on a specific change.

Auto-applies improvements to:
- SL/TP multipliers
- MIN_RR thresholds
- LEVERAGE_CAP
- QUALITY_THRESHOLDS
- REGIME-specific parameters

Changes are committed to GitHub automatically.
"""
import os
import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from collections import Counter
import json
from pathlib import Path

logger = logging.getLogger("algogpt.ai_consensus_improver")

CONSENSUS_THRESHOLD = int(os.getenv("AI_CONSENSUS_THRESHOLD", "3"))  # 3+ brains must agree
AUTO_APPLY_ENABLE = os.getenv("AUTO_APPLY_IMPROVEMENTS", "1") == "1"

IMPROVEMENT_LOG = Path("data/improvements")
IMPROVEMENT_LOG.mkdir(parents=True, exist_ok=True)


@dataclass
class ImprovementProposal:
    parameter: str  # e.g., "SL_MULTIPLIER_CHOPPY", "MIN_RR_TRENDING"
    current_value: Any
    proposed_value: Any
    reason: str
    supporting_brains: List[str]
    confidence: float  # 0-1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "current_value": str(self.current_value),
            "proposed_value": str(self.proposed_value),
            "reason": self.reason,
            "supporting_brains": self.supporting_brains,
            "confidence": self.confidence
        }


class AIConsensusImprover:
    """Analyzes AI reviews and applies consensus-based improvements"""
    
    def __init__(self):
        self.pending_proposals: List[ImprovementProposal] = []
    
    async def analyze_reviews(self, review_results: List[Dict[str, Any]]) -> List[ImprovementProposal]:
        """Analyze multiple trade reviews and extract improvement proposals"""
        all_suggestions = []
        brain_suggestions = {}
        
        for review in review_results:
            for score in review.get("scores", []):
                brain_name = score.get("brain_name")
                suggestions = score.get("suggestions", [])
                
                all_suggestions.extend(suggestions)
                
                if brain_name not in brain_suggestions:
                    brain_suggestions[brain_name] = []
                brain_suggestions[brain_name].extend(suggestions)
        
        proposals = self._extract_actionable_proposals(all_suggestions, brain_suggestions)
        
        logger.info(f"Extracted {len(proposals)} improvement proposals from {len(review_results)} reviews")
        
        return proposals
    
    def _extract_actionable_proposals(self, all_suggestions: List[str], 
                                     brain_suggestions: Dict[str, List[str]]) -> List[ImprovementProposal]:
        """Extract actionable parameter changes from suggestions"""
        proposals = []
        
        suggestion_patterns = {
            "widen_sl_choppy": ("SL_MULTIPLIER_CHOPPY", 2.5, "Wider SL in choppy markets"),
            "tighter_sl_trending": ("SL_MULTIPLIER_TRENDING", 1.8, "Tighter SL in trends"),
            "increase_rr_min": ("MIN_RR", 1.5, "Higher minimum RR"),
            "reduce_leverage": ("LEVERAGE_CAP", 20, "Lower max leverage"),
            "stricter_quality": ("MIN_QUALITY_SCORE", 7.0, "Higher quality threshold"),
            "wider_tp_targets": ("TP_RR_MULTIPLIER", 2.5, "Wider TP targets"),
            "earlier_be": ("BE_AFTER_TP1_PCT", 0.3, "Move to BE earlier"),
        }
        
        for pattern_key, (param, new_value, reason) in suggestion_patterns.items():
            matching_suggestions = [s for s in all_suggestions if pattern_key.replace("_", " ") in s.lower()]
            
            if not matching_suggestions:
                continue
            
            supporting_brains = []
            for brain_name, suggestions in brain_suggestions.items():
                if any(pattern_key.replace("_", " ") in s.lower() for s in suggestions):
                    supporting_brains.append(brain_name)
            
            if len(supporting_brains) >= CONSENSUS_THRESHOLD:
                current_value = self._get_current_param_value(param)
                
                proposal = ImprovementProposal(
                    parameter=param,
                    current_value=current_value,
                    proposed_value=new_value,
                    reason=reason,
                    supporting_brains=supporting_brains,
                    confidence=len(supporting_brains) / 5.0
                )
                
                proposals.append(proposal)
                logger.info(f"✅ Consensus reached: {param} -> {new_value} ({len(supporting_brains)}/5 brains)")
        
        return proposals
    
    def _get_current_param_value(self, param: str) -> Any:
        """Get current parameter value from ENV or config"""
        env_mapping = {
            "SL_MULTIPLIER_CHOPPY": "SL_ATR_MULTIPLIER_CHOPPY",
            "SL_MULTIPLIER_TRENDING": "SL_ATR_MULTIPLIER_TRENDING",
            "MIN_RR": "RR_MIN_MID_VOL",
            "LEVERAGE_CAP": "LEV_HARD_CAP",
            "MIN_QUALITY_SCORE": "MIN_QUALITY_SCORE",
            "TP_RR_MULTIPLIER": "TP_RR_MULTIPLIER",
            "BE_AFTER_TP1_PCT": "BE_AFTER_TP1_PCT"
        }
        
        env_var = env_mapping.get(param, param)
        return os.getenv(env_var, "UNKNOWN")
    
    async def apply_improvements(self, proposals: List[ImprovementProposal]) -> Dict[str, Any]:
        """Apply approved improvements automatically"""
        if not AUTO_APPLY_ENABLE:
            logger.info("Auto-apply disabled. Proposals logged only.")
            self._log_proposals(proposals)
            return {"ok": False, "reason": "auto_apply_disabled", "proposals": len(proposals)}
        
        applied = []
        failed = []
        
        for proposal in proposals:
            try:
                success = await self._apply_single_improvement(proposal)
                if success:
                    applied.append(proposal.parameter)
                    logger.info(f"✅ Applied: {proposal.parameter} = {proposal.proposed_value}")
                else:
                    failed.append(proposal.parameter)
                    logger.warning(f"❌ Failed to apply: {proposal.parameter}")
            except Exception as e:
                logger.error(f"Error applying {proposal.parameter}: {e}")
                failed.append(proposal.parameter)
        
        self._log_proposals(proposals, applied, failed)
        
        if applied:
            await self._commit_to_github(proposals, applied)
        
        return {
            "ok": True,
            "applied": applied,
            "failed": failed,
            "total_proposals": len(proposals)
        }
    
    async def _apply_single_improvement(self, proposal: ImprovementProposal) -> bool:
        """Apply a single parameter improvement"""
        try:
            config_file = Path("config/trading_params.json")
            
            if not config_file.exists():
                config_file.parent.mkdir(parents=True, exist_ok=True)
                config = {}
            else:
                with open(config_file, 'r') as f:
                    config = json.load(f)
            
            config[proposal.parameter] = proposal.proposed_value
            config[f"{proposal.parameter}_UPDATED_BY"] = "AI_Consensus"
            config[f"{proposal.parameter}_REASON"] = proposal.reason
            config[f"{proposal.parameter}_BRAINS"] = proposal.supporting_brains
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"Failed to apply {proposal.parameter}: {e}")
            return False
    
    def _log_proposals(self, proposals: List[ImprovementProposal], 
                      applied: Optional[List[str]] = None, 
                      failed: Optional[List[str]] = None):
        """Log proposals to disk"""
        try:
            import time
            timestamp = int(time.time())
            log_file = IMPROVEMENT_LOG / f"proposals_{timestamp}.json"
            
            log_data = {
                "timestamp": timestamp,
                "proposals": [p.to_dict() for p in proposals],
                "applied": applied or [],
                "failed": failed or []
            }
            
            with open(log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
            
            logger.info(f"Proposals logged: {log_file}")
        except Exception as e:
            logger.error(f"Failed to log proposals: {e}")
    
    async def _commit_to_github(self, proposals: List[ImprovementProposal], applied: List[str]):
        """Commit improvements to GitHub"""
        try:
            from utils.github_auto_commit import commit_ai_improvements
            
            commit_message = f"AI Auto-Improvement: {', '.join(applied)}\n\n"
            commit_message += "Consensus-based parameter optimization:\n"
            
            for proposal in proposals:
                if proposal.parameter in applied:
                    commit_message += f"- {proposal.parameter}: {proposal.current_value} -> {proposal.proposed_value}\n"
                    commit_message += f"  Reason: {proposal.reason}\n"
                    commit_message += f"  Supporting: {', '.join(proposal.supporting_brains)}\n"
            
            result = await commit_ai_improvements(commit_message)
            
            if result.get("ok"):
                logger.info(f"✅ GitHub commit successful: {result.get('commit_sha', 'N/A')}")
            else:
                logger.error(f"❌ GitHub commit failed: {result.get('error')}")
        
        except Exception as e:
            logger.error(f"Failed to commit to GitHub: {e}")


_improver = AIConsensusImprover()


async def analyze_and_apply_improvements(review_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze reviews and apply consensus-based improvements"""
    proposals = await _improver.analyze_reviews(review_results)
    
    if not proposals:
        logger.info("No actionable proposals extracted from reviews")
        return {"ok": True, "proposals": 0, "applied": []}
    
    result = await _improver.apply_improvements(proposals)
    return result
