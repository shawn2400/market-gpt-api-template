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
        
        win_pnls = [t.actual_pnl_usd for t in wins if t.actual_pnl_usd is not None]
        loss_pnls = [t.actual_pnl_usd for t in losses if t.actual_pnl_usd is not None]
        
        return {
            "win_rate": len(wins) / len(filtered_trades) * 100,
            "total_trades": len(filtered_trades),
            "wins": len(wins),
            "losses": len(losses),
            "avg_win_usd": sum(win_pnls) / len(win_pnls) if win_pnls else 0.0,
            "avg_loss_usd": sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
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
    
    def get_expectancy_per_symbol(self, symbol: Optional[str] = None, days: int = 30) -> Dict:
        """
        Calculate expectancy (average $ won/lost per trade) per symbol.
        
        Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
        
        Args:
            symbol: Specific symbol or None for all
            days: Lookback period
            
        Returns:
            Dict with expectancy, win_rate, avg_win, avg_loss per symbol
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        closed_trades = [
            t for t in self.trades
            if t.closed_at is not None
            and t.actual_pnl_usd is not None
            and datetime.fromisoformat(t.opened_at) >= cutoff
        ]
        
        if symbol:
            closed_trades = [t for t in closed_trades if t.symbol == symbol]
        
        # Group by symbol
        symbols = set(t.symbol for t in closed_trades)
        results = {}
        
        for sym in symbols:
            sym_trades = [t for t in closed_trades if t.symbol == sym]
            
            if not sym_trades:
                continue
            
            wins = [t for t in sym_trades if t.win]
            losses = [t for t in sym_trades if not t.win]
            
            win_pnls = [t.actual_pnl_usd for t in wins if t.actual_pnl_usd is not None]
            loss_pnls = [abs(t.actual_pnl_usd) for t in losses if t.actual_pnl_usd is not None]
            
            win_rate = len(wins) / len(sym_trades) if sym_trades else 0.0
            loss_rate = len(losses) / len(sym_trades) if sym_trades else 0.0
            
            avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
            avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
            
            expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
            
            results[sym] = {
                "expectancy_usd": round(expectancy, 2),
                "win_rate": round(win_rate * 100, 1),
                "avg_win_usd": round(avg_win, 2),
                "avg_loss_usd": round(avg_loss, 2),
                "total_trades": len(sym_trades),
                "total_pnl_usd": round(sum(t.actual_pnl_usd for t in sym_trades), 2)
            }
        
        return results
    
    def get_consecutive_stats(self, symbol: Optional[str] = None) -> Dict:
        """
        Track consecutive wins/losses for psychological insights.
        
        Args:
            symbol: Specific symbol or None for all
            
        Returns:
            Dict with current_streak, max_win_streak, max_loss_streak
        """
        closed_trades = [
            t for t in self.trades
            if t.closed_at is not None
            and t.win is not None
        ]
        
        if symbol:
            closed_trades = [t for t in closed_trades if t.symbol == symbol]
        
        if not closed_trades:
            return {
                "current_streak": 0,
                "current_streak_type": "none",
                "max_win_streak": 0,
                "max_loss_streak": 0,
                "avg_win_streak": 0.0,
                "avg_loss_streak": 0.0
            }
        
        # Calculate streaks
        current_streak = 0
        current_streak_type = "none"
        max_win_streak = 0
        max_loss_streak = 0
        current_win_streak = 0
        current_loss_streak = 0
        
        win_streaks = []
        loss_streaks = []
        
        for trade in sorted(closed_trades, key=lambda t: t.opened_at):
            if trade.win:
                current_win_streak += 1
                if current_loss_streak > 0:
                    loss_streaks.append(current_loss_streak)
                    current_loss_streak = 0
            else:
                current_loss_streak += 1
                if current_win_streak > 0:
                    win_streaks.append(current_win_streak)
                    current_win_streak = 0
        
        # Add final streaks
        if current_win_streak > 0:
            win_streaks.append(current_win_streak)
            current_streak = current_win_streak
            current_streak_type = "wins"
        if current_loss_streak > 0:
            loss_streaks.append(current_loss_streak)
            current_streak = current_loss_streak
            current_streak_type = "losses"
        
        max_win_streak = max(win_streaks) if win_streaks else 0
        max_loss_streak = max(loss_streaks) if loss_streaks else 0
        
        return {
            "current_streak": current_streak,
            "current_streak_type": current_streak_type,
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "avg_win_streak": sum(win_streaks) / len(win_streaks) if win_streaks else 0.0,
            "avg_loss_streak": sum(loss_streaks) / len(loss_streaks) if loss_streaks else 0.0,
            "total_win_streaks": len(win_streaks),
            "total_loss_streaks": len(loss_streaks)
        }
    
    def get_best_performing_symbols(self, days: int = 30, min_trades: int = 3) -> List[Dict]:
        """
        Identify best-performing symbols by expectancy.
        
        Args:
            days: Lookback period
            min_trades: Minimum trades for statistical significance
            
        Returns:
            List of symbols sorted by expectancy (best first)
        """
        expectancy_data = self.get_expectancy_per_symbol(days=days)
        
        # Filter by minimum trades and sort by expectancy
        valid_symbols = [
            {
                "symbol": symbol,
                **data
            }
            for symbol, data in expectancy_data.items()
            if data["total_trades"] >= min_trades
        ]
        
        return sorted(valid_symbols, key=lambda x: x["expectancy_usd"], reverse=True)
    
    def get_calibration_recommendations(self) -> Dict:
        """
        Analyze performance and recommend threshold adjustments.
        
        Returns:
            Recommendations for min_rr, quality thresholds, etc.
        """
        overall_perf = self.get_win_rate(days=14)
        regime_perf = self.get_regime_performance(days=14)
        ai_accuracy = self.get_ai_accuracy(days=14)
        expectancy_data = self.get_expectancy_per_symbol(days=14)
        consecutive = self.get_consecutive_stats()
        
        recommendations = {
            "overall_win_rate": overall_perf["win_rate"],
            "total_trades_14d": overall_perf["total_trades"],
            "ai_prediction_error": ai_accuracy["prediction_error"],
            "avg_expectancy_usd": sum(d["expectancy_usd"] for d in expectancy_data.values()) / len(expectancy_data) if expectancy_data else 0.0,
            "current_streak": f"{consecutive['current_streak']} {consecutive['current_streak_type']}",
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
        
        # Check consecutive losses - if in a losing streak, pause or tighten
        if consecutive["current_streak"] >= 3 and consecutive["current_streak_type"] == "losses":
            recommendations["adjustments"].append({
                "parameter": "trading_pause",
                "current": "active",
                "suggestion": "pause for 1 hour",
                "reason": f"In {consecutive['current_streak']} loss streak, take a break"
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
    
    def get_symbol_stats(self, symbol: str, days: int = 30) -> Dict:
        """
        Get comprehensive performance stats for a specific symbol.
        
        Args:
            symbol: The trading symbol
            days: Lookback period (default: 30 days)
            
        Returns:
            Dict with win_rate, avg_profit, avg_loss, total_trades, recent_trend, etc.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        symbol_trades = [
            t for t in self.trades
            if t.symbol == symbol
            and t.closed_at is not None
            and t.actual_pnl_usd is not None
            and datetime.fromisoformat(t.opened_at) >= cutoff
        ]
        
        if not symbol_trades:
            return {
                "symbol": symbol,
                "win_rate": 0.0,
                "avg_profit": 0.0,
                "avg_loss": 0.0,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "recent_trend": "unknown",
                "consecutive_losses": 0,
                "last_trade_date": None
            }
        
        wins = [t for t in symbol_trades if t.win]
        losses = [t for t in symbol_trades if not t.win]
        
        win_pnls = [t.actual_pnl_usd for t in wins]
        loss_pnls = [t.actual_pnl_usd for t in losses]
        
        win_rate = (len(wins) / len(symbol_trades) * 100) if symbol_trades else 0.0
        
        recent_trend = self._calculate_recent_trend(symbol_trades)
        
        consecutive_losses = self._count_consecutive_losses(symbol, days=days)
        
        last_trade = max(symbol_trades, key=lambda t: t.closed_at or t.opened_at)
        
        return {
            "symbol": symbol,
            "win_rate": round(win_rate, 2),
            "avg_profit": round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0.0,
            "avg_loss": round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0.0,
            "total_trades": len(symbol_trades),
            "wins": len(wins),
            "losses": len(losses),
            "recent_trend": recent_trend,
            "consecutive_losses": consecutive_losses,
            "last_trade_date": last_trade.closed_at or last_trade.opened_at
        }
    
    def get_all_symbol_stats(self, days: int = 30, min_trades: int = 3) -> Dict[str, Dict]:
        """
        Get performance stats for all symbols that have minimum trade count.
        
        Args:
            days: Lookback period
            min_trades: Minimum trades required to include symbol
            
        Returns:
            Dict mapping symbol -> stats
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        recent_trades = [
            t for t in self.trades
            if t.closed_at is not None
            and datetime.fromisoformat(t.opened_at) >= cutoff
        ]
        
        symbols = set(t.symbol for t in recent_trades)
        
        all_stats = {}
        for symbol in symbols:
            stats = self.get_symbol_stats(symbol, days=days)
            if stats["total_trades"] >= min_trades:
                all_stats[symbol] = stats
        
        return all_stats
    
    def _calculate_recent_trend(self, trades: List[TradeRecord]) -> str:
        """
        Analyze if performance is improving, stable, or declining.
        
        Compares recent 50% vs older 50% of trades.
        """
        if len(trades) < 6:
            return "insufficient_data"
        
        sorted_trades = sorted(trades, key=lambda t: t.opened_at)
        
        midpoint = len(sorted_trades) // 2
        older_half = sorted_trades[:midpoint]
        recent_half = sorted_trades[midpoint:]
        
        older_wins = sum(1 for t in older_half if t.win)
        recent_wins = sum(1 for t in recent_half if t.win)
        
        older_wr = (older_wins / len(older_half) * 100) if older_half else 0.0
        recent_wr = (recent_wins / len(recent_half) * 100) if recent_half else 0.0
        
        diff = recent_wr - older_wr
        
        if diff > 15:
            return "improving"
        elif diff < -15:
            return "declining"
        else:
            return "stable"
    
    def _count_consecutive_losses(self, symbol: str, days: int = 30) -> int:
        """Count consecutive losses for a symbol (most recent first)"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        symbol_trades = [
            t for t in self.trades
            if t.symbol == symbol
            and t.closed_at is not None
            and t.win is not None
            and datetime.fromisoformat(t.opened_at) >= cutoff
        ]
        
        if not symbol_trades:
            return 0
        
        sorted_trades = sorted(symbol_trades, key=lambda t: t.closed_at or t.opened_at, reverse=True)
        
        consecutive = 0
        for trade in sorted_trades:
            if not trade.win:
                consecutive += 1
            else:
                break
        
        return consecutive
    
    def get_consecutive_losses(self, days: int = 7) -> int:
        """Get total consecutive losses across all symbols (for circuit breaker)"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        all_trades = [
            t for t in self.trades
            if t.closed_at is not None
            and t.win is not None
            and datetime.fromisoformat(t.opened_at) >= cutoff
        ]
        
        if not all_trades:
            return 0
        
        sorted_trades = sorted(all_trades, key=lambda t: t.closed_at or t.opened_at, reverse=True)
        
        consecutive = 0
        for trade in sorted_trades:
            if not trade.win:
                consecutive += 1
            else:
                break
        
        return consecutive


# Global instance
_performance_tracker = None

def get_performance_tracker() -> PerformanceTracker:
    """Get singleton instance of PerformanceTracker"""
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker
