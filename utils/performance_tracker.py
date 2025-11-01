"""
Performance Tracker - Continuous Learning System
=================================================
Tracks trade performance to enable auto-calibration and strategy optimization.

Features:
- Win rate per strategy type (Regular/GRID/Scalp)
- Win rate per market regime (Trending/Sideways/Choppy)
- Average RR achieved vs predicted
- Success rate per AI confidence level
- Auto-calibration of thresholds based on performance

Author: AlgoGPT Team
Level: Hedge Fund Grade
"""

import logging
import os
import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, asdict

LOGGER = logging.getLogger("performance_tracker")


@dataclass
class TradeRecord:
    """Single trade record for performance analysis"""
    symbol: str
    side: str
    strategy: str  # "futures_long", "futures_short", "grid", etc
    market_regime: str  # "trending", "sideways", "choppy", "volatile"
    market_mood: str  # "bullish", "bearish", "neutral"
    
    # Predicted metrics
    predicted_rr: float
    predicted_success_pct: float
    ai_confidence: float
    
    # Actual metrics
    actual_rr: Optional[float] = None
    actual_pnl_usd: Optional[float] = None
    win: Optional[bool] = None
    
    # Timestamps
    opened_at: str = ""
    closed_at: Optional[str] = None
    
    # Metadata
    quality_score: Optional[float] = None
    volatility_class: Optional[str] = None


class PerformanceTracker:
    """
    Tracks all trades and calculates performance metrics for optimization.
    
    Learning capabilities:
    - Which market regimes perform best?
    - Which strategies have highest win rate?
    - Are AI predictions accurate?
    - Should we adjust thresholds?
    """
    
    def __init__(self):
        self.logger = LOGGER
        self.trades: List[TradeRecord] = []
        self.persistence_file = os.getenv(
            "PERFORMANCE_TRACKER_FILE",
            "/tmp/performance_tracker.json"
        )
        self._load_from_disk()
    
    def record_trade_opened(
        self,
        symbol: str,
        side: str,
        strategy: str,
        market_regime: str,
        market_mood: str,
        predicted_rr: float,
        predicted_success_pct: float,
        ai_confidence: float,
        quality_score: Optional[float] = None,
        volatility_class: Optional[str] = None
    ) -> str:
        """
        Record a new trade opening.
        
        Returns:
            trade_id for later reference
        """
        trade = TradeRecord(
            symbol=symbol,
            side=side,
            strategy=strategy,
            market_regime=market_regime,
            market_mood=market_mood,
            predicted_rr=predicted_rr,
            predicted_success_pct=predicted_success_pct,
            ai_confidence=ai_confidence,
            quality_score=quality_score,
            volatility_class=volatility_class,
            opened_at=datetime.utcnow().isoformat()
        )
        
        self.trades.append(trade)
        self._save_to_disk()
        
        trade_id = f"{symbol}_{side}_{trade.opened_at}"
        self.logger.info(f"📝 Trade recorded: {trade_id}")
        return trade_id
    
    def record_trade_closed(
        self,
        symbol: str,
        side: str,
        actual_pnl_usd: float,
        actual_rr: Optional[float] = None
    ):
        """Record a trade closing with results"""
        # Find the most recent open trade for this symbol/side
        for trade in reversed(self.trades):
            if trade.symbol == symbol and trade.side == side and trade.closed_at is None:
                trade.closed_at = datetime.utcnow().isoformat()
                trade.actual_pnl_usd = actual_pnl_usd
                trade.actual_rr = actual_rr
                trade.win = (actual_pnl_usd > 0)
                
                self._save_to_disk()
                
                self.logger.info(
                    f"📝 Trade closed: {symbol} {side}, "
                    f"PnL=${actual_pnl_usd:+.2f}, "
                    f"Win={trade.win}"
                )
                
                # Log learning insights
                self._log_learning_insight(trade)
                break
    
    def get_win_rate(
        self,
        strategy: Optional[str] = None,
        market_regime: Optional[str] = None,
        market_mood: Optional[str] = None,
        days: int = 7
    ) -> Dict:
        """
        Calculate win rate with optional filters.
        
        Args:
            strategy: Filter by strategy type
            market_regime: Filter by market regime
            market_mood: Filter by market mood
            days: Look back period
            
        Returns:
            Dict with win_rate, total_trades, wins, losses
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        filtered_trades = [
            t for t in self.trades
            if t.closed_at is not None
            and t.win is not None
            and datetime.fromisoformat(t.opened_at) >= cutoff
        ]
        
        # Apply filters
        if strategy:
            filtered_trades = [t for t in filtered_trades if t.strategy == strategy]
        if market_regime:
            filtered_trades = [t for t in filtered_trades if t.market_regime == market_regime]
        if market_mood:
            filtered_trades = [t for t in filtered_trades if t.market_mood == market_mood]
        
        if not filtered_trades:
            return {
                "win_rate": 0.0,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "avg_win_usd": 0.0,
                "avg_loss_usd": 0.0
            }
        
        wins = [t for t in filtered_trades if t.win]
        losses = [t for t in filtered_trades if not t.win]
        
        return {
            "win_rate": len(wins) / len(filtered_trades) * 100,
            "total_trades": len(filtered_trades),
            "wins": len(wins),
            "losses": len(losses),
            "avg_win_usd": sum(t.actual_pnl_usd for t in wins) / len(wins) if wins else 0.0,
            "avg_loss_usd": sum(t.actual_pnl_usd for t in losses) / len(losses) if losses else 0.0
        }
    
    def get_strategy_performance(self, days: int = 7) -> Dict[str, Dict]:
        """Get performance breakdown by strategy"""
        strategies = set(t.strategy for t in self.trades if t.strategy)
        
        return {
            strategy: self.get_win_rate(strategy=strategy, days=days)
            for strategy in strategies
        }
    
    def get_regime_performance(self, days: int = 7) -> Dict[str, Dict]:
        """Get performance breakdown by market regime"""
        regimes = set(t.market_regime for t in self.trades if t.market_regime)
        
        return {
            regime: self.get_win_rate(market_regime=regime, days=days)
            for regime in regimes
        }
    
    def get_ai_accuracy(self, days: int = 7) -> Dict:
        """Analyze AI prediction accuracy"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        closed_trades = [
            t for t in self.trades
            if t.closed_at is not None
            and t.win is not None
            and datetime.fromisoformat(t.opened_at) >= cutoff
        ]
        
        if not closed_trades:
            return {
                "prediction_accuracy": 0.0,
                "avg_predicted_success": 0.0,
                "actual_win_rate": 0.0,
                "prediction_error": 0.0
            }
        
        avg_predicted = sum(t.predicted_success_pct for t in closed_trades) / len(closed_trades)
        actual_win_rate = len([t for t in closed_trades if t.win]) / len(closed_trades) * 100
        
        return {
            "prediction_accuracy": 100 - abs(avg_predicted - actual_win_rate),
            "avg_predicted_success": avg_predicted,
            "actual_win_rate": actual_win_rate,
            "prediction_error": avg_predicted - actual_win_rate,
            "total_trades": len(closed_trades)
        }
    
    def get_calibration_recommendations(self) -> Dict:
        """
        Analyze performance and recommend threshold adjustments.
        
        Returns:
            Recommendations for min_rr, quality thresholds, etc.
        """
        overall_perf = self.get_win_rate(days=14)
        regime_perf = self.get_regime_performance(days=14)
        ai_accuracy = self.get_ai_accuracy(days=14)
        
        recommendations = {
            "overall_win_rate": overall_perf["win_rate"],
            "total_trades_14d": overall_perf["total_trades"],
            "ai_prediction_error": ai_accuracy["prediction_error"],
            "adjustments": []
        }
        
        # If win rate is very high, we can afford to be more aggressive
        if overall_perf["win_rate"] > 70 and overall_perf["total_trades"] >= 10:
            recommendations["adjustments"].append({
                "parameter": "min_rr_threshold",
                "current": "adaptive",
                "suggestion": "lower by 0.1",
                "reason": f"Win rate {overall_perf['win_rate']:.1f}% is excellent, can take more trades"
            })
        
        # If win rate is low, tighten requirements
        if overall_perf["win_rate"] < 50 and overall_perf["total_trades"] >= 10:
            recommendations["adjustments"].append({
                "parameter": "min_rr_threshold",
                "current": "adaptive",
                "suggestion": "increase by 0.2",
                "reason": f"Win rate {overall_perf['win_rate']:.1f}% is low, need better quality"
            })
        
        # Check which regimes perform best
        best_regime = max(
            regime_perf.items(),
            key=lambda x: x[1]["win_rate"] if x[1]["total_trades"] >= 3 else 0,
            default=(None, None)
        )
        if best_regime[0] and best_regime[1]:
            recommendations["best_regime"] = {
                "regime": best_regime[0],
                "win_rate": best_regime[1]["win_rate"],
                "trades": best_regime[1]["total_trades"]
            }
        
        return recommendations
    
    def generate_weekly_report(self) -> str:
        """Generate human-readable weekly performance report"""
        overall = self.get_win_rate(days=7)
        strategies = self.get_strategy_performance(days=7)
        regimes = self.get_regime_performance(days=7)
        ai_acc = self.get_ai_accuracy(days=7)
        calibration = self.get_calibration_recommendations()
        
        report = f"""
📊 **AlgoGPT Performance Report - Last 7 Days**

**Overall Performance:**
- Win Rate: {overall['win_rate']:.1f}%
- Total Trades: {overall['total_trades']}
- Wins: {overall['wins']} | Losses: {overall['losses']}
- Avg Win: ${overall['avg_win_usd']:+.2f}
- Avg Loss: ${overall['avg_loss_usd']:+.2f}

**AI Prediction Accuracy:**
- Predicted Success: {ai_acc['avg_predicted_success']:.1f}%
- Actual Win Rate: {ai_acc['actual_win_rate']:.1f}%
- Prediction Error: {ai_acc['prediction_error']:+.1f}%

**Performance by Strategy:**
"""
        for strategy, perf in strategies.items():
            if perf["total_trades"] > 0:
                report += f"- {strategy}: {perf['win_rate']:.1f}% ({perf['total_trades']} trades)\n"
        
        report += "\n**Performance by Market Regime:**\n"
        for regime, perf in regimes.items():
            if perf["total_trades"] > 0:
                report += f"- {regime}: {perf['win_rate']:.1f}% ({perf['total_trades']} trades)\n"
        
        if calibration.get("adjustments"):
            report += "\n**📈 Calibration Recommendations:**\n"
            for adj in calibration["adjustments"]:
                report += f"- {adj['parameter']}: {adj['suggestion']} ({adj['reason']})\n"
        
        return report
    
    # ========== Internal Methods ==========
    
    def _log_learning_insight(self, trade: TradeRecord):
        """Log insights from individual trade results"""
        if trade.win:
            self.logger.info(
                f"✅ WIN: {trade.symbol} {trade.strategy} in {trade.market_regime} market, "
                f"predicted RR={trade.predicted_rr:.2f}, actual PnL=${trade.actual_pnl_usd:+.2f}"
            )
        else:
            self.logger.info(
                f"❌ LOSS: {trade.symbol} {trade.strategy} in {trade.market_regime} market, "
                f"predicted RR={trade.predicted_rr:.2f}, actual PnL=${trade.actual_pnl_usd:+.2f}"
            )
    
    def _save_to_disk(self):
        """Persist trades to disk"""
        try:
            data = [asdict(t) for t in self.trades]
            with open(self.persistence_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save performance data: {e}")
    
    def _load_from_disk(self):
        """Load trades from disk"""
        try:
            if os.path.exists(self.persistence_file):
                with open(self.persistence_file, "r") as f:
                    data = json.load(f)
                    self.trades = [TradeRecord(**t) for t in data]
                    self.logger.info(f"Loaded {len(self.trades)} historical trades")
        except Exception as e:
            self.logger.warning(f"Failed to load performance data: {e}")
            self.trades = []


# Global instance
_performance_tracker = None

def get_performance_tracker() -> PerformanceTracker:
    """Get singleton instance of PerformanceTracker"""
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker
