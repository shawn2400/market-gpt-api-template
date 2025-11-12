#!/usr/bin/env python3
"""
Scout Data Builder
Combines Market Intelligence + Strategy Orchestrator outputs into unified scout_data
"""
import logging
from typing import Dict, Any

logger = logging.getLogger("algogpt.scout_data_builder")


def build_scout_data(
    symbol: str,
    market_intelligence_result: Dict[str, Any],
    strategy_orchestrator_result: Dict[str, Any],
    market_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build unified scout_data from 2 Scouts.
    
    Args:
        symbol: Trading symbol (e.g. BTCUSDT)
        market_intelligence_result: Result from Market Intelligence Brain
        strategy_orchestrator_result: Result from Strategy Orchestrator
        market_data: Raw market indicators
    
    Returns:
        Unified scout_data dict ready for 5 AI Brains
    """
    
    mi_score = market_intelligence_result.get("quality_score", 5.0)
    so_score = strategy_orchestrator_result.get("score", 5.0)
    avg_score = (mi_score + so_score) / 2.0
    
    scout_data = {
        "symbol": symbol,
        "strategy": strategy_orchestrator_result.get("strategy", "NONE"),
        
        "market_scanner": {
            "score": mi_score,
            "regime": market_intelligence_result.get("regime", "UNKNOWN"),
            "reasoning": market_intelligence_result.get("reasoning", "No reasoning"),
            "quality_score": mi_score
        },
        
        "technical_analyst": {
            "score": so_score,
            "strategy": strategy_orchestrator_result.get("strategy", "NONE"),
            "reasoning": strategy_orchestrator_result.get("reasoning", "No reasoning"),
            "signals": strategy_orchestrator_result.get("signals", [])
        },
        
        "avg_score": avg_score,
        
        "min_rr": strategy_orchestrator_result.get("min_rr", 1.1),
        "min_quality": strategy_orchestrator_result.get("min_quality", 6.0),  # Dynamic quality threshold
        "leverage": strategy_orchestrator_result.get("leverage", 5),
        "sl_atr_mult": strategy_orchestrator_result.get("sl_atr_mult", 1.5),
        "tp_rr": strategy_orchestrator_result.get("tp_rr", 1.5),
        
        "market_data": market_data,
        
        "timestamp": market_intelligence_result.get("timestamp") or strategy_orchestrator_result.get("timestamp")
    }
    
    logger.info(
        f"Scout Data Built: {symbol} | {scout_data['strategy']} | "
        f"MI={mi_score:.1f} SO={so_score:.1f} AVG={avg_score:.1f}"
    )
    
    return scout_data


__all__ = ["build_scout_data"]
