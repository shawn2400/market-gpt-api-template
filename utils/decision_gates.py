# utils/decision_gates.py
"""
Fail-Closed Decision Gates
===========================
Dual Confirmation System: Quant ∧ AI ∧ Risk
No permissive fallbacks - FAIL CLOSED on missing data.
"""

from __future__ import annotations
import os
import logging
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("decision_gates")

@dataclass
class DualGateConfig:
    """Configuration for dual-gate decision system"""
    quant_min_score: float
    ai_min_score: float
    min_rr: float
    require_all_data: bool
    
    @classmethod
    def from_env(cls) -> "DualGateConfig":
        return cls(
            quant_min_score=float(os.getenv("QUANT_MIN_SCORE", "0.70")),
            ai_min_score=float(os.getenv("AI_MIN_SCORE", "0.70")),
            min_rr=float(os.getenv("MIN_EXPECTED_RR", "1.45")),
            require_all_data=os.getenv("DISABLE_PERMISSIVE_FALLBACKS", "1") == "1",
        )

class CriticalDataMissing(Exception):
    """Raised when critical data is missing and fail-closed is enabled"""
    pass

def dual_gate_decision(
    quant_score: Optional[float],
    ai_score: Optional[float],
    rr: Optional[float],
    risk_ok: bool,
    *,
    cfg: Optional[DualGateConfig] = None,
) -> Tuple[bool, str]:
    """
    Strict dual-gate approval system.
    
    Args:
        quant_score: Quantitative signal score (0-1)
        ai_score: AI analysis score (0-1)
        rr: Risk-reward ratio
        risk_ok: Risk checks passed
        cfg: Configuration (uses env defaults if None)
        
    Returns:
        (approved: bool, reason: str)
        
    Raises:
        CriticalDataMissing: If fail-closed mode and data missing
    """
    if cfg is None:
        cfg = DualGateConfig.from_env()
    
    # FAIL-CLOSED: Check for missing critical data
    if cfg.require_all_data:
        if quant_score is None:
            raise CriticalDataMissing("Quant score missing - cannot proceed without quantitative validation")
        if ai_score is None:
            raise CriticalDataMissing("AI score missing - cannot proceed without AI validation")
        if rr is None:
            raise CriticalDataMissing("RR missing - cannot proceed without risk-reward calculation")
    
    # Handle None values with defaults (only if NOT fail-closed)
    quant = quant_score if quant_score is not None else 0.0
    ai = ai_score if ai_score is not None else 0.0
    risk_reward = rr if rr is not None else 0.0
    
    # Dual Confirmation: ALL must pass
    quant_pass = quant >= cfg.quant_min_score
    ai_pass = ai >= cfg.ai_min_score
    rr_pass = risk_reward >= cfg.min_rr
    risk_pass = risk_ok
    
    # Build detailed reason
    reasons = []
    if not quant_pass:
        reasons.append(f"quant_score={quant:.2f}<{cfg.quant_min_score:.2f}")
    if not ai_pass:
        reasons.append(f"ai_score={ai:.2f}<{cfg.ai_min_score:.2f}")
    if not rr_pass:
        reasons.append(f"rr={risk_reward:.2f}<{cfg.min_rr:.2f}")
    if not risk_pass:
        reasons.append("risk_checks_failed")
    
    approved = quant_pass and ai_pass and rr_pass and risk_pass
    
    if approved:
        reason = f"APPROVED: quant={quant:.2f}, ai={ai:.2f}, rr={risk_reward:.2f}, risk=OK"
        logger.info(reason)
    else:
        reason = f"BLOCKED: {', '.join(reasons)}"
        logger.warning(reason)
    
    return (approved, reason)

def validate_trade_proposal(proposal: Dict[str, Any]) -> Tuple[bool, str]:
    """
    High-level trade validation using dual-gate system.
    
    Args:
        proposal: Trade proposal dict with:
            - quant_score: Quantitative score
            - ai_score: AI confidence
            - expected_rr: Risk-reward ratio
            - risk_passed: Risk check result
            
    Returns:
        (approved, reason)
    """
    try:
        approved, reason = dual_gate_decision(
            quant_score=proposal.get("quant_score"),
            ai_score=proposal.get("ai_score"),
            rr=proposal.get("expected_rr"),
            risk_ok=proposal.get("risk_passed", False),
        )
        return (approved, reason)
    
    except CriticalDataMissing as e:
        reason = f"BLOCKED: {str(e)}"
        logger.error(reason)
        return (False, reason)
    
    except Exception as e:
        reason = f"BLOCKED: Unexpected error in dual-gate - {str(e)}"
        logger.error(reason, exc_info=True)
        return (False, reason)
