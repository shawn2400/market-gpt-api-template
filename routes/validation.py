# routes/validation.py
"""
Validation & Backtesting API Endpoints
========================================
Production-grade validation pipeline endpoints.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import uuid
import logging

from utils.validation import run_backtest, BacktestResult

logger = logging.getLogger("routes.validation")

router = APIRouter(prefix="/validate", tags=["validation"])

# REMOVED: In-memory storage - now using database persistence

class BacktestRequest(BaseModel):
    symbols: List[str]
    strategy: str = "sop_v3"
    start: str = "-240d"
    end: str = "now"
    folds: int = 6

class BacktestStatus(BaseModel):
    id: str
    status: str  # "running", "completed", "failed"
    progress: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@router.post("/run")
async def run_validation(request: BacktestRequest, background_tasks: BackgroundTasks):
    """
    Start a backtest validation run.
    
    Returns immediately with run_id for status checking.
    """
    from utils.db import USE_DB, _conn
    import json, time
    
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required for validation - set USE_DB=1")
    
    run_id = f"bt_{uuid.uuid4().hex[:12]}"
    
    # Persist run to database
    try:
        with _conn() as con:
            cur = con.cursor()
            cur.execute("""INSERT INTO bt_runs 
                (id, strategy, start_date, end_date, folds, status)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, request.strategy, request.start, request.end, request.folds, "running")
            )
            con.commit()
    except Exception as e:
        logger.error(f"Failed to initialize backtest run in DB: {e}")
        raise HTTPException(status_code=500, detail=f"Database initialization failed: {e}")
    
    # Start backtest in background
    background_tasks.add_task(_run_backtest_async, run_id, request)
    
    logger.info(f"Backtest {run_id} started for {len(request.symbols)} symbols")
    
    return {
        "run_id": run_id,
        "status": "started",
        "message": f"Backtest started for {len(request.symbols)} symbols",
        "check_status_url": f"/validate/status?id={run_id}",
    }

@router.get("/status")
async def get_validation_status(id: str):
    """
    Check status of a backtest run.
    """
    from utils.db import USE_DB, _conn
    import json
    
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required - set USE_DB=1")
    
    try:
        with _conn() as con:
            cur = con.cursor()
            cur.execute("SELECT status, summary_json FROM bt_runs WHERE id = ?", (id,))
            row = cur.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Backtest run {id} not found")
            
            status, summary_json = row
            result = json.loads(summary_json) if summary_json else None
            
            return BacktestStatus(
                id=id,
                status=status,
                progress=100 if status == "completed" else (50 if status == "running" else 0),
                result=result,
                error=None if status != "failed" else "Backtest failed - check logs",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch backtest status: {e}")
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

@router.get("/report")
async def get_validation_report(id: str):
    """
    Get detailed validation report.
    """
    from utils.db import USE_DB, _conn
    import json
    
    if not USE_DB:
        raise HTTPException(status_code=503, detail="Database required - set USE_DB=1")
    
    try:
        with _conn() as con:
            cur = con.cursor()
            cur.execute("SELECT status, summary_json, strategy, start_date, end_date, folds FROM bt_runs WHERE id = ?", (id,))
            row = cur.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Backtest run {id} not found")
            
            status, summary_json, strategy, start_date, end_date, folds = row
            
            if status != "completed":
                raise HTTPException(
                    status_code=400,
                    detail=f"Backtest {id} not completed yet (status: {status})"
                )
            
            if not summary_json:
                raise HTTPException(status_code=500, detail="Backtest completed but no results found")
            
            result = json.loads(summary_json)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch backtest report: {e}")
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")
    
    # Build comprehensive report
    overall = result.get("overall", {})
    by_regime = result.get("by_regime", {})
    per_symbol = result.get("per_symbol", {})
    sample = result.get("sample", {})
    
    # Validation verdict
    winrate = overall.get("winrate", 0)
    avg_rr = overall.get("avg_rr", 0)
    max_dd = overall.get("max_dd", 0)
    
    # Thresholds from ENV (same as backtest logic)
    min_winrate = 46
    min_rr = 1.45
    max_drawdown = 12
    
    validation_pass = (
        winrate >= min_winrate and
        avg_rr >= min_rr and
        max_dd <= max_drawdown
    )
    
    report = {
        "run_id": id,
        "validation_pass": validation_pass,
        "verdict": "✅ APPROVED FOR PRODUCTION" if validation_pass else "❌ FAILED VALIDATION",
        "overall_metrics": overall,
        "by_regime": by_regime,
        "per_symbol": per_symbol,
        "sample_info": sample,
        "thresholds": {
            "min_winrate_pct": min_winrate,
            "min_rr": min_rr,
            "max_drawdown_pct": max_drawdown,
        },
        "request": {
            "strategy": strategy,
            "start_date": start_date,
            "end_date": end_date,
            "folds": folds,
        },
    }
    
    return report

async def _run_backtest_async(run_id: str, request: BacktestRequest):
    """
    Run backtest asynchronously and update status.
    """
    from utils.db import USE_DB, _conn
    import json, time
    
    try:
        logger.info(f"Starting backtest {run_id}")
        
        # Run backtest
        result: BacktestResult = await run_backtest(
            symbols=request.symbols,
            strategy=request.strategy,
            start=request.start,
            end=request.end,
            walk_forward_folds=request.folds,
        )
        
        # Convert dataclass to dict
        result_dict = {
            "overall": result.overall,
            "by_regime": result.by_regime,
            "per_symbol": result.per_symbol,
            "sample": result.sample,
            "total_trades": len(result.trades),
        }
        
        # Save to database
        if not USE_DB:
            raise RuntimeError("Database required - set USE_DB=1")
        
        with _conn() as con:
            cur = con.cursor()
            cur.execute("""UPDATE bt_runs 
                SET status = ?, summary_json = ?
                WHERE id = ?""",
                ("completed", json.dumps(result_dict), run_id)
            )
            con.commit()
        
        logger.info(f"Backtest {run_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Backtest {run_id} failed: {e}", exc_info=True)
        
        # Mark as failed in database
        try:
            if USE_DB:
                with _conn() as con:
                    cur = con.cursor()
                    cur.execute("UPDATE bt_runs SET status = ? WHERE id = ?", ("failed", run_id))
                    con.commit()
        except Exception as db_err:
            logger.error(f"Failed to update DB status: {db_err}")
