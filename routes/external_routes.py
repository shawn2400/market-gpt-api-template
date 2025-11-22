"""
External Brain Integration Routes — FastAPI endpoints
"""
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from external.plugin_manager import PluginManager
from algo_core.hybrid_router import HybridRouter
from algo_core.consensus_engine import ConsensusEngine
from algo_core.self_optimizer import SelfOptimizer
from algo_core.capability_detector import upgrade_plan, downgrade_plan
import logging

logger = logging.getLogger("ExternalRoutes")

router = APIRouter(prefix="/external", tags=["external"])

# Global instances
pm: Optional[PluginManager] = None
hybrid_router: Optional[HybridRouter] = None
consensus_engine: Optional[ConsensusEngine] = None
optimizer: Optional[SelfOptimizer] = None

def init_external_brain() -> None:
    """Initialize external brain system"""
    global pm, hybrid_router, consensus_engine, optimizer
    
    pm = PluginManager()
    pm.load_all()
    
    hybrid_router = HybridRouter(pm)
    consensus_engine = ConsensusEngine()
    optimizer = SelfOptimizer()
    
    logger.info("✅ External Brain initialized")

@router.get("/status")
async def get_external_status() -> Dict[str, Any]:
    """Get status of all external bots"""
    if not pm:
        init_external_brain()
    
    return {
        "bots": pm.get_status() if pm else {},
        "total": len(pm.plugins) if pm else 0
    }

@router.post("/control/{bot_name}/{mode}")
async def control_bot(bot_name: str, mode: str) -> Dict[str, Any]:
    """Control bot (on/off/auto)"""
    if not pm:
        init_external_brain()
    
    if mode not in ["on", "off", "auto"]:
        raise HTTPException(status_code=400, detail="Invalid mode")
    
    if pm is None:
        raise HTTPException(status_code=500, detail="Plugin manager not initialized")
    
    result = pm.set_mode(bot_name, mode)
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result

@router.post("/plan/{bot_name}/{plan_type}")
async def change_plan(bot_name: str, plan_type: str) -> Dict[str, Any]:
    """Change bot plan (free/paid)"""
    if plan_type == "paid":
        upgrade_plan(bot_name)
        return {"status": "upgraded", "bot": bot_name, "plan": "paid"}
    elif plan_type == "free":
        downgrade_plan(bot_name)
        return {"status": "downgraded", "bot": bot_name, "plan": "free"}
    else:
        raise HTTPException(status_code=400, detail="Invalid plan type")

@router.get("/analyze")
async def analyze_market() -> Dict[str, Any]:
    """Get merged market analysis from all bots"""
    if not hybrid_router or not consensus_engine:
        init_external_brain()
    
    if hybrid_router is None or consensus_engine is None:
        raise HTTPException(status_code=500, detail="System not initialized")
    
    scans = await hybrid_router.get_scans()
    signals = await hybrid_router.get_signals()
    merged = consensus_engine.merge(scans, signals)
    
    return {
        "candidates": merged,
        "total": len(merged),
        "scans_sources": len(scans),
        "signal_sources": len(signals)
    }

@router.get("/scores")
async def get_bot_scores() -> Dict[str, Any]:
    """Get current bot performance scores"""
    if not pm:
        init_external_brain()
    
    if pm is None:
        return {"scores": {}, "top_performer": None}
    
    scores = {}
    for name, plugin in pm.plugins.items():
        scores[name] = plugin.score
    
    return {
        "scores": scores,
        "top_performer": max(scores.items(), key=lambda x: x[1])[0] if scores else None
    }
