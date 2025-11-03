# utils/ai_tracker.py
# -*- coding: utf-8 -*-
"""
בס"ד
AI Performance Tracking & Model Accuracy Analytics
Tracks predictions vs outcomes, calculates Win%, and enables dynamic model weighting
"""
from __future__ import annotations
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Literal
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger("algogpt.ai_tracker")

# File-based storage (will migrate to DB in P1-2)
TRACKER_DATA_DIR = Path("data/ai_tracking")
TRACKER_DATA_DIR.mkdir(parents=True, exist_ok=True)

PREDICTIONS_FILE = TRACKER_DATA_DIR / "predictions.jsonl"
OUTCOMES_FILE = TRACKER_DATA_DIR / "outcomes.jsonl"
PERFORMANCE_CACHE = TRACKER_DATA_DIR / "performance_cache.json"

AIModel = Literal["gpt5", "deepseek", "grok", "consensus"]
MarketRegime = Literal["TRENDING", "RANGING", "VOLATILE", "UNKNOWN"]


@dataclass
class AIPrediction:
    """AI prediction record"""
    prediction_id: str
    timestamp: str
    symbol: str
    ai_model: AIModel
    confidence: float
    prediction: Dict[str, Any]  # Contains side, entry, sl, tp, rr, quality
    regime: MarketRegime
    features: Dict[str, Any]  # Technical indicators snapshot
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradeOutcome:
    """Trade outcome record"""
    outcome_id: str
    prediction_id: str
    timestamp: str
    symbol: str
    pnl_usd: float
    pnl_pct: float
    rr_achieved: float
    time_in_trade_minutes: int
    exit_reason: str  # 'tp1', 'tp2', 'sl', 'manual', 'timeout'
    was_successful: bool  # True if TP hit, False if SL hit
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModelPerformance:
    """AI model performance metrics"""
    model: AIModel
    regime: MarketRegime
    timeframe_days: int
    total_predictions: int
    total_outcomes: int
    wins: int
    losses: int
    win_rate: float
    avg_rr_achieved: float
    avg_pnl_pct: float
    total_pnl_usd: float
    consistency_score: float  # Std dev of returns (lower = more consistent)
    last_updated: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def log_prediction(
    symbol: str,
    ai_model: AIModel,
    confidence: float,
    prediction: Dict[str, Any],
    regime: MarketRegime = "UNKNOWN",
    features: Optional[Dict[str, Any]] = None
) -> str:
    """
    Log AI prediction for future tracking.
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        ai_model: Which AI model made the prediction
        confidence: AI confidence score (0-1)
        prediction: Full prediction dict (side, entry, sl, tp, rr, quality)
        regime: Market regime at prediction time
        features: Technical indicators snapshot
    
    Returns:
        prediction_id for linking to outcomes
    """
    try:
        prediction_id = f"{symbol}_{ai_model}_{int(datetime.now().timestamp())}"
        
        pred = AIPrediction(
            prediction_id=prediction_id,
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            ai_model=ai_model,
            confidence=confidence,
            prediction=prediction,
            regime=regime,
            features=features or {}
        )
        
        # Append to JSONL file
        with open(PREDICTIONS_FILE, "a") as f:
            f.write(json.dumps(pred.to_dict()) + "\n")
        
        logger.info(f"✅ Logged prediction: {prediction_id} (model={ai_model}, confidence={confidence:.2f})")
        return prediction_id
        
    except Exception as e:
        logger.error(f"❌ Failed to log prediction: {e}", exc_info=True)
        return ""


def log_outcome(
    prediction_id: str,
    symbol: str,
    pnl_usd: float,
    pnl_pct: float,
    rr_achieved: float,
    time_in_trade_minutes: int,
    exit_reason: str,
    was_successful: bool
) -> bool:
    """
    Log trade outcome linked to prediction.
    
    Args:
        prediction_id: ID from log_prediction()
        symbol: Trading pair
        pnl_usd: P&L in USD
        pnl_pct: P&L as percentage
        rr_achieved: Actual Risk/Reward achieved
        time_in_trade_minutes: Duration of trade
        exit_reason: How trade exited ('tp1', 'tp2', 'sl', etc.)
        was_successful: True if TP hit, False if SL
    
    Returns:
        True if logged successfully
    """
    try:
        outcome_id = f"{prediction_id}_outcome"
        
        outcome = TradeOutcome(
            outcome_id=outcome_id,
            prediction_id=prediction_id,
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            rr_achieved=rr_achieved,
            time_in_trade_minutes=time_in_trade_minutes,
            exit_reason=exit_reason,
            was_successful=was_successful
        )
        
        # Append to JSONL file
        with open(OUTCOMES_FILE, "a") as f:
            f.write(json.dumps(outcome.to_dict()) + "\n")
        
        logger.info(f"✅ Logged outcome: {outcome_id} (P&L=${pnl_usd:.2f}, RR={rr_achieved:.2f})")
        
        # Invalidate performance cache
        _invalidate_cache()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to log outcome: {e}", exc_info=True)
        return False


def calculate_model_accuracy(
    ai_model: AIModel,
    regime: Optional[MarketRegime] = None,
    timeframe_days: int = 7
) -> Optional[ModelPerformance]:
    """
    Calculate performance metrics for an AI model.
    
    Args:
        ai_model: Which model to analyze
        regime: Filter by market regime (None = all regimes)
        timeframe_days: Look back period (7, 30, 90, etc.)
    
    Returns:
        ModelPerformance object with Win%, Avg RR, etc.
    """
    try:
        # Load predictions and outcomes
        predictions = _load_predictions(ai_model, regime, timeframe_days)
        outcomes = _load_outcomes()
        
        if not predictions:
            logger.warning(f"No predictions found for {ai_model} in last {timeframe_days} days")
            return None
        
        # Match predictions to outcomes
        matched_outcomes = []
        for pred in predictions:
            pred_id = pred["prediction_id"]
            outcome = next((o for o in outcomes if o["prediction_id"] == pred_id), None)
            if outcome:
                matched_outcomes.append(outcome)
        
        if not matched_outcomes:
            logger.warning(f"No outcomes found for {ai_model} predictions")
            return None
        
        # Calculate metrics
        wins = sum(1 for o in matched_outcomes if o["was_successful"])
        losses = len(matched_outcomes) - wins
        win_rate = wins / len(matched_outcomes) if matched_outcomes else 0.0
        
        avg_rr = sum(o["rr_achieved"] for o in matched_outcomes) / len(matched_outcomes)
        avg_pnl_pct = sum(o["pnl_pct"] for o in matched_outcomes) / len(matched_outcomes)
        total_pnl = sum(o["pnl_usd"] for o in matched_outcomes)
        
        # Consistency score (lower = more consistent)
        pnl_values = [o["pnl_pct"] for o in matched_outcomes]
        consistency = _calculate_std_dev(pnl_values) if len(pnl_values) > 1 else 0.0
        
        perf = ModelPerformance(
            model=ai_model,
            regime=regime if regime else "UNKNOWN",  # type: ignore
            timeframe_days=timeframe_days,
            total_predictions=len(predictions),
            total_outcomes=len(matched_outcomes),
            wins=wins,
            losses=losses,
            win_rate=round(win_rate * 100, 2),
            avg_rr_achieved=round(avg_rr, 2),
            avg_pnl_pct=round(avg_pnl_pct, 2),
            total_pnl_usd=round(total_pnl, 2),
            consistency_score=round(consistency, 2),
            last_updated=datetime.now().isoformat()
        )
        
        logger.info(f"📊 {ai_model} ({timeframe_days}d): Win%={perf.win_rate}%, Avg RR={perf.avg_rr_achieved}")
        
        return perf
        
    except Exception as e:
        logger.error(f"❌ Failed to calculate model accuracy: {e}", exc_info=True)
        return None


def get_model_leaderboard(timeframe_days: int = 7) -> List[ModelPerformance]:
    """
    Get leaderboard of all AI models sorted by Win%.
    
    Args:
        timeframe_days: Look back period
    
    Returns:
        List of ModelPerformance sorted by Win% descending
    """
    try:
        models: List[str] = ["gpt5", "deepseek", "grok", "consensus"]
        leaderboard = []
        
        for model in models:
            perf = calculate_model_accuracy(model, timeframe_days=timeframe_days)  # type: ignore
            if perf:
                leaderboard.append(perf)
        
        # Sort by Win% descending
        leaderboard.sort(key=lambda x: x.win_rate, reverse=True)
        
        logger.info(f"🏆 Leaderboard ({timeframe_days}d): {len(leaderboard)} models")
        for idx, perf in enumerate(leaderboard, 1):
            logger.info(f"  #{idx} {perf.model}: {perf.win_rate}% Win Rate, {perf.avg_rr_achieved} Avg RR")
        
        return leaderboard
        
    except Exception as e:
        logger.error(f"❌ Failed to get leaderboard: {e}", exc_info=True)
        return []


def get_dynamic_weights(regime: MarketRegime = "UNKNOWN", timeframe_days: int = 7) -> Dict[AIModel, float]:
    """
    Calculate dynamic weights for AI models based on recent performance.
    
    Args:
        regime: Current market regime
        timeframe_days: Performance look-back period
    
    Returns:
        Dict mapping model → weight (sum = 1.0)
    """
    try:
        base_weights = {
            "gpt5": 0.50,
            "deepseek": 0.30,
            "grok": 0.20
        }
        
        # Calculate performance-based adjustments
        adjusted_weights = base_weights.copy()
        
        for model in base_weights.keys():
            perf = calculate_model_accuracy(model, regime, timeframe_days)
            
            if perf and perf.total_outcomes >= 5:  # Minimum 5 trades for adjustment
                win_rate = perf.win_rate / 100.0  # Convert to 0-1
                
                if win_rate > 0.60:
                    adjusted_weights[model] *= 1.2  # Boost high performers
                    logger.info(f"⬆️ Boosting {model}: {win_rate:.1%} Win Rate")
                elif win_rate < 0.45:
                    adjusted_weights[model] *= 0.8  # Reduce low performers
                    logger.info(f"⬇️ Reducing {model}: {win_rate:.1%} Win Rate")
        
        # Normalize to sum = 1.0
        total = sum(adjusted_weights.values())
        normalized: Dict[AIModel, float] = {k: round(v / total, 3) for k, v in adjusted_weights.items()}  # type: ignore
        
        logger.info(f"⚖️ Dynamic weights ({regime}, {timeframe_days}d): {normalized}")
        
        return normalized
        
    except Exception as e:
        logger.error(f"❌ Failed to calculate dynamic weights: {e}", exc_info=True)
        return {"gpt5": 0.50, "deepseek": 0.30, "grok": 0.20}


# ==================== Private Helpers ====================

def _load_predictions(
    ai_model: Optional[AIModel] = None,
    regime: Optional[MarketRegime] = None,
    timeframe_days: int = 7
) -> List[Dict[str, Any]]:
    """Load predictions from JSONL file with filters"""
    try:
        if not PREDICTIONS_FILE.exists():
            return []
        
        cutoff = datetime.now() - timedelta(days=timeframe_days)
        predictions = []
        
        with open(PREDICTIONS_FILE, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                pred = json.loads(line)
                
                # Filter by timestamp
                pred_time = datetime.fromisoformat(pred["timestamp"])
                if pred_time < cutoff:
                    continue
                
                # Filter by model
                if ai_model and pred["ai_model"] != ai_model:
                    continue
                
                # Filter by regime
                if regime and pred.get("regime") != regime:
                    continue
                
                predictions.append(pred)
        
        return predictions
        
    except Exception as e:
        logger.error(f"Failed to load predictions: {e}", exc_info=True)
        return []


def _load_outcomes() -> List[Dict[str, Any]]:
    """Load all outcomes from JSONL file"""
    try:
        if not OUTCOMES_FILE.exists():
            return []
        
        outcomes = []
        with open(OUTCOMES_FILE, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                outcomes.append(json.loads(line))
        
        return outcomes
        
    except Exception as e:
        logger.error(f"Failed to load outcomes: {e}", exc_info=True)
        return []


def _calculate_std_dev(values: List[float]) -> float:
    """Calculate standard deviation"""
    if len(values) < 2:
        return 0.0
    
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return variance ** 0.5


def _invalidate_cache():
    """Invalidate performance cache when new outcomes are logged"""
    try:
        if PERFORMANCE_CACHE.exists():
            PERFORMANCE_CACHE.unlink()
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")


__all__ = [
    "log_prediction",
    "log_outcome",
    "calculate_model_accuracy",
    "get_model_leaderboard",
    "get_dynamic_weights",
    "AIPrediction",
    "TradeOutcome",
    "ModelPerformance",
    "AIModel",
    "MarketRegime"
]
