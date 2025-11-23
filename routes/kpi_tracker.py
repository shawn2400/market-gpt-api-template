#!/usr/bin/env python3
# routes/kpi_tracker.py
"""
KPI Tracker Routes - Priority 3
===============================
Expose KPI dashboard endpoints:
- Auto-Switch Counter
- SL-Saves Tracker
- Missed Trades Logger
- Locked Profit Display
"""

from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import logging

from utils.kpi_tracker import get_tracker
from utils.rbac import require_user

logger = logging.getLogger("algogpt.routes.kpi_tracker")
router = APIRouter(prefix="/kpi", tags=["kpi-tracker"])


@router.get("/summary")
async def get_kpi_summary(current_user = Depends(require_user)):
    """
    Get complete KPI summary for user
    
    Hebrew: קבל סיכום KPI מלא למשתמש
    
    Returns:
    - auto_switch_count: Number of admin switches today
    - sl_saves: SL-save counter + profit
    - missed_trades_count: Number of missed trade proposals
    - locked_profit_daily: Cumulative locked profit from stages
    """
    try:
        tracker = await get_tracker()
        summary = await tracker.get_kpi_summary(current_user.id)
        return JSONResponse(summary)
    except Exception as e:
        logger.error(f"Failed to get KPI summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auto-switch")
async def get_auto_switch_count(
    period: str = "day",
    current_user = Depends(require_user)
):
    """
    Get auto-switch counter
    
    Hebrew: קבל דלק הפעלות אוטומטיות של משתמש
    
    Params:
    - period: "day" or "total"
    
    Returns:
    - count: Number of switches in period
    """
    try:
        tracker = await get_tracker()
        count = await tracker.get_auto_switch_count(current_user.id, period)
        return {
            "user_id": current_user.id,
            "period": period,
            "count": count,
            "display": f"🔄 {count} switches"
        }
    except Exception as e:
        logger.error(f"Failed to get auto-switch count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sl-saves")
async def get_sl_saves(
    period: str = "day",
    current_user = Depends(require_user)
):
    """
    Get SL-saves counter + profit
    
    Hebrew: קבל דלק SL-Saves + רווח
    
    Params:
    - period: "day" or "total"
    
    Returns:
    - count: Number of SL saves
    - profit: Total profit saved by SL management
    """
    try:
        tracker = await get_tracker()
        sl_saves = await tracker.get_sl_saves(current_user.id, period)
        return {
            "user_id": current_user.id,
            "period": period,
            "count": sl_saves["count"],
            "profit": sl_saves["profit"],
            "display": f"💰 {sl_saves['count']} saves (${sl_saves['profit']:.2f})"
        }
    except Exception as e:
        logger.error(f"Failed to get SL-saves: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missed-trades")
async def get_missed_trades(
    period: str = "day",
    limit: int = 50,
    current_user = Depends(require_user)
):
    """
    Get missed trades data
    
    Hebrew: קבל נתוני טריידים שלא בוצעו
    
    Params:
    - period: "day" or "total"
    - limit: Max number of details to return
    
    Returns:
    - count: Number of missed trades
    - details: List of missed trade details
    - reasons: Breakdown by reason
    """
    try:
        tracker = await get_tracker()
        missed = await tracker.get_missed_trades(current_user.id, period, limit)
        return {
            "user_id": current_user.id,
            "period": period,
            "count": missed["count"],
            "details": missed["details"],
            "reasons": missed["reasons"],
            "display": f"⚠️ {missed['count']} missed"
        }
    except Exception as e:
        logger.error(f"Failed to get missed trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/locked-profit")
async def get_locked_profit(
    period: str = "day",
    current_user = Depends(require_user)
):
    """
    Get locked profit from SL/TP stages
    
    Hebrew: קבל רווח נעול מ-SL/TP stages
    
    Params:
    - period: "day" or "total"
    
    Returns:
    - daily/total: Locked profit amount in specified period
    """
    try:
        tracker = await get_tracker()
        profit = await tracker.get_locked_profit(current_user.id, period)
        
        amount = profit.get(period, 0.0)
        return {
            "user_id": current_user.id,
            "period": period,
            "amount": amount,
            "display": f"🔒 ${amount:.2f} locked"
        }
    except Exception as e:
        logger.error(f"Failed to get locked profit: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/locked-profit/events")
async def get_locked_profit_events(
    limit: int = 50,
    current_user = Depends(require_user)
):
    """
    Get locked profit events timeline
    
    Hebrew: קבל סדרת אירועים של רווח נעול
    
    Params:
    - limit: Max number of events
    
    Returns:
    - events: List of locked profit events with details
    """
    try:
        tracker = await get_tracker()
        events = await tracker.get_locked_profit_events(current_user.id, limit)
        return {
            "user_id": current_user.id,
            "count": len(events),
            "events": events
        }
    except Exception as e:
        logger.error(f"Failed to get locked profit events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auto-switch/track")
async def track_auto_switch(
    from_user_id: str,
    to_user_id: str,
    current_user = Depends(require_user)
):
    """
    Track admin auto-switch (called by admin user)
    
    Hebrew: עקוב אחרי החלפת משתמש אוטומטית
    
    Internal use - called by auto-switch endpoint
    """
    try:
        tracker = await get_tracker()
        await tracker.increment_auto_switch(to_user_id, from_user_id)
        return {"status": "tracked"}
    except Exception as e:
        logger.error(f"Failed to track auto-switch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sl-save/track")
async def track_sl_save(
    symbol: str,
    saved_amount: float = 0.0,
    current_user = Depends(require_user)
):
    """
    Track SL-save event
    
    Hebrew: עקוב אחרי SL-Save
    
    Internal use - called when SL management saves a position
    """
    try:
        tracker = await get_tracker()
        await tracker.increment_sl_save(current_user.id, symbol, saved_amount)
        return {"status": "tracked"}
    except Exception as e:
        logger.error(f"Failed to track SL-save: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missed-trade/track")
async def track_missed_trade(
    symbol: str,
    reason: str = "unknown",
    entry: float = 0.0,
    current_user = Depends(require_user)
):
    """
    Track missed trade proposal
    
    Hebrew: עקוב אחרי טרייד שלא בוצע
    
    Internal use - called when trade is rejected
    """
    try:
        tracker = await get_tracker()
        await tracker.log_missed_trade(current_user.id, symbol, reason, entry)
        return {"status": "tracked"}
    except Exception as e:
        logger.error(f"Failed to track missed trade: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/locked-profit/track")
async def track_locked_profit(
    symbol: str,
    amount: float,
    stage: int = 0,
    current_user = Depends(require_user)
):
    """
    Track locked profit event
    
    Hebrew: עקוב אחרי אירוע רווח נעול
    
    Internal use - called when SL/TP stage locks profit
    """
    try:
        tracker = await get_tracker()
        await tracker.add_locked_profit(current_user.id, symbol, amount, stage)
        return {"status": "tracked"}
    except Exception as e:
        logger.error(f"Failed to track locked profit: {e}")
        raise HTTPException(status_code=500, detail=str(e))
