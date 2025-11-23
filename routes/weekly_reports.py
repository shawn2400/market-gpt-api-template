# -*- coding: utf-8 -*-
"""
Priority 4: Weekly Reports Routes - API endpoints for weekly report management.
"""

from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Optional, Dict, Any
from datetime import datetime
import logging
from contextlib import suppress

from utils.weekly_reporter import get_weekly_reporter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weekly", tags=["Weekly Reports"])


@router.get("/status")
async def get_weekly_report_status() -> Dict[str, Any]:
    """Get status of weekly report system."""
    reporter = get_weekly_reporter()
    
    return {
        "enabled": reporter.enabled,
        "last_report": reporter.get_last_report(),
        "should_generate": reporter.should_generate_report(),
        "timestamp": datetime.utcnow().isoformat()
    }


@router.post("/generate")
async def generate_weekly_report(trades: Optional[list] = None) -> Dict[str, Any]:
    """
    Manually trigger weekly report generation.
    Useful for testing or force-running reports.
    """
    reporter = get_weekly_reporter()
    
    if not reporter.enabled:
        raise HTTPException(status_code=400, detail="Weekly reporter is disabled")
    
    # Use provided trades or empty list
    if trades is None:
        trades = []
    
    try:
        report = reporter.generate_report(trades)
        return {
            "status": "success",
            "report": report
        }
    except Exception as e:
        logger.error(f"Failed to generate weekly report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/last")
async def get_last_weekly_report() -> Dict[str, Any]:
    """Get the last generated weekly report."""
    reporter = get_weekly_reporter()
    
    last_report = reporter.get_last_report()
    
    if not last_report:
        raise HTTPException(status_code=404, detail="No weekly report generated yet")
    
    return last_report


@router.get("/schedule")
async def get_weekly_report_schedule() -> Dict[str, Any]:
    """Get weekly report generation schedule."""
    from utils.weekly_reporter import REPORT_DAY, REPORT_TIME
    
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    return {
        "day": days[int(REPORT_DAY)],
        "time": REPORT_TIME,
        "timezone": "UTC",
        "description": f"Weekly report generated every {days[int(REPORT_DAY)]} at {REPORT_TIME} UTC"
    }


@router.get("/format/telegram")
async def get_telegram_format_sample(pnl: float = 100.50) -> Dict[str, str]:
    """Get sample Telegram report format."""
    reporter = get_weekly_reporter()
    
    sample_stats = {
        "total_trades": 15,
        "winning_trades": 10,
        "losing_trades": 5,
        "win_rate": 0.667,
        "total_pnl": pnl,
        "avg_pnl_per_trade": pnl / 15,
        "best_trade": 25.50,
        "worst_trade": -12.30,
        "sharpe_ratio": 1.25,
        "symbols_traded": ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    }
    
    return {
        "format": "HTML",
        "content": reporter.format_telegram_report(sample_stats)
    }


@router.get("/format/email")
async def get_email_format_sample(pnl: float = 100.50) -> Dict[str, Any]:
    """Get sample email report format."""
    reporter = get_weekly_reporter()
    
    sample_stats = {
        "total_trades": 15,
        "winning_trades": 10,
        "losing_trades": 5,
        "win_rate": 0.667,
        "total_pnl": pnl,
        "avg_pnl_per_trade": pnl / 15,
        "best_trade": 25.50,
        "worst_trade": -12.30,
        "sharpe_ratio": 1.25,
        "symbols_traded": ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    }
    
    email_data = reporter.format_email_report(sample_stats)
    
    return {
        "html": email_data["html"][:200] + "...",  # Preview
        "text_preview": email_data["text"][:300] + "..."
    }


@router.get("/health")
async def weekly_report_health() -> Dict[str, Any]:
    """Health check for weekly report system."""
    reporter = get_weekly_reporter()
    
    return {
        "status": "healthy" if reporter.enabled else "disabled",
        "enabled": reporter.enabled,
        "last_report_timestamp": reporter.last_report_ts,
        "reports_generated": 1 if reporter.report_cache else 0
    }
