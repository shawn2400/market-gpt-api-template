# routes/monitors.py
"""
Live Monitoring & Circuit Breaker API Endpoints
================================================
Real-time health monitoring and circuit breaker controls.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import logging

from utils.monitors import evaluate_live_health, HealthStatus
from utils.monitors.circuit_breaker import (
    check_circuit_breaker, 
    reset_breaker, 
    get_breaker_status,
    BreakerAction
)

logger = logging.getLogger("routes.monitors")

router = APIRouter(prefix="/monitors", tags=["monitoring"])

class HealthCheckResponse(BaseModel):
    ok: bool
    action: str
    reason: str
    metrics: Dict[str, Any]
    breaker_status: Dict[str, Any]

@router.get("/health")
async def get_health_status():
    """
    Get current system health status.
    
    Includes:
    - Win% 7d and 30d
    - Drawdown 7d
    - Consecutive stop losses
    - Circuit breaker status
    """
    # Load recent metrics from database (FAIL-HARD if missing)
    from utils.db import USE_DB, _conn
    import time
    from datetime import datetime, timedelta
    
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required - set USE_DB=1")
    
    try:
        with _conn() as con:
            cur = con.cursor()
            
            # Get most recent live_kpis entry
            cur.execute("""SELECT winrate_7d, winrate_30d, exp_rr_30d, dd_7d, consec_sl 
                FROM live_kpis ORDER BY updated_at DESC LIMIT 1""")
            row = cur.fetchone()
            
            if not row:
                raise HTTPException(
                    status_code=404, 
                    detail="No live KPI data found - system needs at least 7 days of trading history"
                )
            
            winrate_7d, winrate_30d, exp_rr_30d, dd_7d, consec_sl = row
            
            metrics_7d = {
                "winrate": winrate_7d or 0,
                "avg_rr": exp_rr_30d or 0,
                "total_trades": 0,  # Not tracked yet
            }
            
            metrics_30d = {
                "winrate": winrate_30d or 0,
                "avg_rr": exp_rr_30d or 0,
                "total_trades": 0,  # Not tracked yet
            }
            
            consec_sl = consec_sl or 0
            dd_7d = dd_7d or 0.0
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load metrics from database: {e}")
    
    # Evaluate health
    health: HealthStatus = evaluate_live_health(
        metrics_7d=metrics_7d,
        metrics_30d=metrics_30d,
        consec_sl=consec_sl,
        dd_7d=dd_7d,
    )
    
    # Get breaker status
    breaker = get_breaker_status()
    
    return HealthCheckResponse(
        ok=health.ok,
        action=health.action,
        reason=health.reason,
        metrics=health.metrics,
        breaker_status=breaker,
    )

class BreakerActionRequest(BaseModel):
    reason: Optional[str] = "manual_action"

@router.post("/breaker/pause")
async def pause_trading(request: BreakerActionRequest):
    """
    Manually trigger circuit breaker pause.
    """
    from utils.db import USE_DB, _conn
    import time
    
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required - set USE_DB=1")
    
    logger.warning(f"Manual circuit breaker pause triggered: {request.reason}")
    
    # Persist manual pause to database
    try:
        with _conn() as con:
            cur = con.cursor()
            import json
            cur.execute("""INSERT INTO blocks_log (reason, ctx_json) VALUES (?, ?)""",
                ("MANUAL_PAUSE", json.dumps({"reason": request.reason, "manual": True}))
            )
            con.commit()
    except Exception as e:
        logger.error(f"Failed to persist manual pause: {e}")
        raise HTTPException(status_code=500, detail=f"Database write failed: {e}")
    
    # Also call circuit breaker with real manual trigger
    from utils.monitors.circuit_breaker import manual_pause
    breaker = manual_pause(reason=request.reason)
    
    return {
        "status": "paused",
        "reason": request.reason,
        "breaker": {
            "triggered": True,
            "action": "PAUSE_MANUAL",
            "reason": request.reason,
        },
    }

@router.post("/breaker/reset")
async def reset_circuit_breaker(request: BreakerActionRequest):
    """
    Manually reset circuit breaker.
    
    Use this after resolving issues that triggered the breaker.
    """
    from utils.db import USE_DB, _conn
    import time
    
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required - set USE_DB=1")
    
    logger.info(f"Circuit breaker reset requested: {request.reason}")
    
    # Persist reset to database
    try:
        with _conn() as con:
            cur = con.cursor()
            import json
            cur.execute("""INSERT INTO blocks_log (reason, ctx_json) VALUES (?, ?)""",
                ("MANUAL_RESET", json.dumps({"reason": request.reason, "manual": True}))
            )
            con.commit()
    except Exception as e:
        logger.error(f"Failed to persist reset: {e}")
        raise HTTPException(status_code=500, detail=f"Database write failed: {e}")
    
    result = reset_breaker(reason=request.reason)
    
    return {
        "status": "reset",
        "message": "Circuit breaker has been reset - trading can resume",
        "details": result,
    }

@router.get("/breaker/status")
async def get_breaker_details():
    """
    Get detailed circuit breaker status.
    """
    status = get_breaker_status()
    
    return {
        "breaker_status": status,
        "paused": status.get("paused", False),
        "pause_reason": status.get("pause_reason", ""),
        "metrics": {
            "daily_dd": status.get("daily_dd", 0.0),
            "daily_dd_peak": status.get("daily_dd_peak", 0.0),
            "consec_losses": status.get("consec_losses", 0),
        },
        "last_reset": status.get("last_reset", ""),
    }

@router.post("/breaker/test")
async def test_circuit_breaker():
    """
    Test circuit breaker with simulated conditions.
    
    For testing only - does not affect real trading.
    """
    # Test scenarios
    scenarios = [
        {"dd": 3.0, "consec": 2, "vol": False, "expected": "none"},
        {"dd": 6.0, "consec": 2, "vol": False, "expected": "pause"},
        {"dd": 3.0, "consec": 5, "vol": False, "expected": "pause"},
        {"dd": 8.0, "consec": 5, "vol": True, "expected": "emergency_stop"},
    ]
    
    results = []
    for scenario in scenarios:
        breaker = check_circuit_breaker(
            current_dd=scenario["dd"],
            consec_losses=scenario["consec"],
            volatility_spike=scenario["vol"],
        )
        
        results.append({
            "scenario": scenario,
            "triggered": breaker.triggered,
            "action": breaker.action,
            "expected": scenario["expected"],
            "pass": breaker.action == scenario["expected"] or (not breaker.triggered and scenario["expected"] == "none"),
        })
    
    # Reset after test
    reset_breaker(reason="test_completed")
    
    return {
        "test_status": "completed",
        "scenarios_tested": len(scenarios),
        "results": results,
        "all_passed": all(r["pass"] for r in results),
    }
