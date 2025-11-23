# -*- coding: utf-8 -*-
"""
ULTRA-PLUS: Feature Routes - API endpoints for all ULTRA-PLUS systems.
Heatmap, ML Predictor, Freeze Manager, Profit-Share, Insurance, Anomaly Detection.
"""

from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Optional, Dict, Any
from datetime import datetime
import logging

from utils.ml_predictor import get_ml_predictor
from utils.freeze_manager import get_freeze_manager
from utils.performance_heatmap import get_performance_heatmap
from utils.profit_share import get_profit_share_manager
from utils.auto_withdraw import get_auto_withdraw_manager
from utils.insurance_mode import get_insurance_mode
from utils.anomaly_detector import get_anomaly_detector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ultra", tags=["ULTRA-PLUS Features"])


# =============== ML Predictor ===============

@router.get("/ml/status")
async def ml_predictor_status() -> Dict[str, Any]:
    """Get ML predictor status and last prediction."""
    ml = get_ml_predictor()
    
    return {
        "enabled": ml.enabled,
        "window_size": ml.window,
        "prices_collected": len(ml.prices),
        "last_prediction": ml.last_prediction,
        "ready": len(ml.prices) >= max(3, ml.window // 2)
    }


@router.get("/ml/predict")
async def ml_predict_now() -> Dict[str, Any]:
    """Get current ML prediction."""
    ml = get_ml_predictor()
    
    prediction = ml.predict()
    
    if not prediction:
        return {
            "status": "insufficient_data",
            "required_prices": max(3, ml.window // 2),
            "current_prices": len(ml.prices)
        }
    
    return prediction


# =============== Freeze Manager ===============

@router.get("/freeze/status")
async def freeze_manager_status() -> Dict[str, Any]:
    """Get status of all frozen symbols."""
    freeze = get_freeze_manager()
    
    frozen = freeze.get_all_frozen()
    
    return {
        "enabled": freeze.enabled,
        "frozen_count": len(frozen),
        "frozen_symbols": frozen
    }


@router.post("/freeze/{symbol}")
async def freeze_symbol(symbol: str, minutes: int = 180, 
                       reason: str = "manual") -> Dict[str, Any]:
    """Manually freeze a symbol from trading."""
    freeze = get_freeze_manager()
    
    success = freeze.freeze(symbol, minutes, reason)
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to freeze symbol")
    
    return {
        "status": "success",
        "symbol": symbol,
        "frozen_until": freeze.get_freeze_info(symbol)
    }


@router.delete("/freeze/{symbol}")
async def unfreeze_symbol(symbol: str) -> Dict[str, Any]:
    """Unfreeze a symbol."""
    freeze = get_freeze_manager()
    
    success = freeze.unfreeze(symbol)
    
    if not success:
        raise HTTPException(status_code=404, detail="Symbol not frozen")
    
    return {"status": "success", "symbol": symbol, "unfrozen": True}


@router.post("/freeze/all/unfreeze")
async def unfreeze_all() -> Dict[str, Any]:
    """Unfreeze all symbols."""
    freeze = get_freeze_manager()
    count = freeze.unfreeze_all()
    
    return {"status": "success", "unfrozen_count": count}


# =============== Performance Heatmap ===============

@router.get("/heatmap")
async def heatmap_summary() -> Dict[str, Any]:
    """Get performance heatmap summary."""
    heatmap = get_performance_heatmap()
    
    return heatmap.export()


@router.get("/heatmap/mode/{mode}")
async def heatmap_mode_stats(mode: str) -> Dict[str, Any]:
    """Get statistics for a specific market mode."""
    heatmap = get_performance_heatmap()
    summary = heatmap.summary()
    
    if mode not in summary:
        raise HTTPException(status_code=404, detail=f"Mode {mode} has no data")
    
    return {"mode": mode, "stats": summary[mode]}


# =============== Profit-Share System ===============

@router.get("/billing/pending/{user_id}")
async def get_pending_billing(user_id: str) -> Dict[str, Any]:
    """Get pending billing for a user."""
    ps = get_profit_share_manager()
    
    return ps.get_pending(user_id)


@router.get("/billing/history/{user_id}")
async def get_billing_history(user_id: str, limit: int = Query(50, le=500)) -> Dict[str, Any]:
    """Get billing history for a user."""
    ps = get_profit_share_manager()
    
    history = ps.get_billing_history(user_id)
    
    return {
        "user_id": user_id,
        "total_records": len(history),
        "history": history[-limit:]
    }


@router.post("/billing/mark-paid/{user_id}")
async def mark_billing_paid(user_id: str) -> Dict[str, Any]:
    """Mark pending billing as paid."""
    ps = get_profit_share_manager()
    
    success = ps.mark_paid(user_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="No pending billing for user")
    
    return {"status": "success", "user_id": user_id}


# =============== Auto-Withdraw ===============

@router.get("/withdraw/status")
async def auto_withdraw_status() -> Dict[str, Any]:
    """Get auto-withdraw system status."""
    aw = get_auto_withdraw_manager()
    
    return aw.get_status()


@router.get("/withdraw/history")
async def withdraw_history(limit: int = Query(50, le=500)) -> Dict[str, Any]:
    """Get withdrawal history."""
    aw = get_auto_withdraw_manager()
    
    history = aw.get_withdrawal_history(limit)
    
    return {
        "total_withdrawals": len(history),
        "history": history
    }


# =============== Insurance Mode ===============

@router.get("/insurance/status")
async def insurance_status() -> Dict[str, Any]:
    """Get insurance mode status."""
    insurance = get_insurance_mode()
    
    return insurance.get_status()


@router.post("/insurance/evaluate")
async def evaluate_insurance(
    funding_rate: float = 0.0,
    volatility: float = 0.0
) -> Dict[str, Any]:
    """Evaluate if insurance measures should activate."""
    insurance = get_insurance_mode()
    
    recommendation = insurance.evaluate(
        funding_rate=funding_rate,
        volatility=volatility
    )
    
    return recommendation


@router.post("/insurance/deactivate")
async def deactivate_insurance() -> Dict[str, Any]:
    """Manually deactivate insurance mode."""
    insurance = get_insurance_mode()
    
    success = insurance.deactivate()
    
    return {
        "status": "success" if success else "already_inactive",
        "active": insurance.active
    }


# =============== Anomaly Detector ===============

@router.get("/anomaly/stats")
async def anomaly_stats() -> Dict[str, Any]:
    """Get anomaly detector statistics."""
    detector = get_anomaly_detector()
    
    return detector.get_stats()


@router.post("/anomaly/add-trade")
async def add_trade_for_anomaly(pnl: float, symbol: str = "", 
                                side: str = "") -> Dict[str, Any]:
    """Add a trade to anomaly detection window."""
    detector = get_anomaly_detector()
    
    detector.add_trade(pnl, symbol, side)
    
    anomaly = detector.detect()
    
    return {
        "status": "success",
        "anomaly_detected": anomaly is not None,
        "anomaly": anomaly,
        "stats": detector.get_stats()
    }


# =============== ULTRA-PLUS System Status ===============

@router.get("/status")
async def ultra_plus_system_status() -> Dict[str, Any]:
    """Get complete ULTRA-PLUS system status."""
    ml = get_ml_predictor()
    freeze = get_freeze_manager()
    heatmap = get_performance_heatmap()
    ps = get_profit_share_manager()
    aw = get_auto_withdraw_manager()
    insurance = get_insurance_mode()
    detector = get_anomaly_detector()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "systems": {
            "ml_predictor": {
                "enabled": ml.enabled,
                "ready": len(ml.prices) >= max(3, ml.window // 2)
            },
            "freeze_manager": {
                "enabled": freeze.enabled,
                "frozen_count": len(freeze.frozen_symbols)
            },
            "performance_heatmap": {
                "enabled": heatmap.enabled,
                "total_trades": heatmap.total_trades
            },
            "profit_share": {
                "enabled": ps.enabled,
                "rate": ps.profit_share_rate
            },
            "auto_withdraw": {
                "enabled": aw.enabled,
                "configured": bool(aw.cold_wallet)
            },
            "insurance_mode": {
                "enabled": insurance.enabled,
                "active": insurance.active
            },
            "anomaly_detector": {
                "enabled": detector.enabled,
                "anomalies_detected": detector.anomaly_count
            }
        }
    }


@router.get("/health")
async def ultra_plus_health() -> Dict[str, Any]:
    """Health check for all ULTRA-PLUS systems."""
    try:
        status = await ultra_plus_system_status()
        return {
            "status": "healthy",
            "systems_online": 7,
            "last_check": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"ULTRA-PLUS health check failed: {e}")
        raise HTTPException(status_code=500, detail="ULTRA-PLUS system error")
