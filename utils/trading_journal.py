# utils/trading_journal.py
"""
📝 Trading Journal & Analytics
Automatic trade logging, performance analysis, weekly reports, pattern recognition
"""

from __future__ import annotations
import os
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
import statistics

logger = logging.getLogger("algogpt.trading_journal")


class TradeOutcome(Enum):
    """תוצאת עסקה"""
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"


class ExitReason(Enum):
    """סיבת יציאה"""
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    BREAKEVEN = "breakeven"
    MANUAL = "manual"
    TIMEOUT = "timeout"
    EMERGENCY = "emergency"


@dataclass
class TradeJournalEntry:
    """רשומת עסקה ביומן"""
    trade_id: str
    symbol: str
    direction: str  # "long" or "short"
    entry_time: float
    exit_time: Optional[float]
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    leverage: float
    
    # SL/TP
    initial_sl: float
    initial_tp: float
    final_sl: Optional[float]
    final_tp: Optional[float]
    
    # Performance
    pnl_usd: Optional[float]
    pnl_pct: Optional[float]
    outcome: Optional[TradeOutcome]
    exit_reason: Optional[ExitReason]
    
    # Market context
    atr: float
    market_regime: Optional[str]
    quality_score: Optional[float]
    combo_used: Optional[str]
    
    # Metadata
    tags: List[str]
    notes: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for storage"""
        data = asdict(self)
        # Convert enums to strings
        if data.get('outcome'):
            data['outcome'] = data['outcome'].value if isinstance(data['outcome'], TradeOutcome) else data['outcome']
        if data.get('exit_reason'):
            data['exit_reason'] = data['exit_reason'].value if isinstance(data['exit_reason'], ExitReason) else data['exit_reason']
        return data


@dataclass
class PerformanceMetrics:
    """מדדי ביצועים"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    
    total_pnl: float
    largest_win: float
    largest_loss: float
    
    avg_hold_time: float  # in hours
    avg_leverage: float


class TradingJournal:
    """
    📝 יומן מסחר אוטומטי עם analytics
    
    Features:
    - רישום עסקאות אוטומטי
    - ניתוח ביצועים
    - דוחות שבועיים/חודשיים
    - זיהוי דפוסים
    - tracking של combos ביצועים
    """
    
    def __init__(self, storage_path: str = "data/trading_journal.json"):
        self.storage_path = storage_path
        self.trades: Dict[str, TradeJournalEntry] = {}
        
        # Ensure data directory exists
        import os
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        
        self._load_journal()
    
    def _load_journal(self):
        """טוען יומן מהדיסק"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    for trade_id, trade_data in data.items():
                        # Reconstruct enums
                        if trade_data.get('outcome'):
                            trade_data['outcome'] = TradeOutcome(trade_data['outcome'])
                        if trade_data.get('exit_reason'):
                            trade_data['exit_reason'] = ExitReason(trade_data['exit_reason'])
                        
                        self.trades[trade_id] = TradeJournalEntry(**trade_data)
                
                logger.info(f"📝 Loaded {len(self.trades)} trades from journal")
        except Exception as e:
            logger.warning(f"Failed to load journal: {e}")
    
    def _save_journal(self):
        """שומר יומן לדיסק"""
        try:
            data = {trade_id: trade.to_dict() for trade_id, trade in self.trades.items()}
            
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"💾 Saved {len(self.trades)} trades to journal")
        except Exception as e:
            logger.warning(f"Failed to save journal: {e}")
    
    def record_entry(
        self,
        trade_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: float,
        leverage: float,
        initial_sl: float,
        initial_tp: float,
        atr: float,
        quality_score: Optional[float] = None,
        combo_used: Optional[str] = None,
        market_regime: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: str = ""
    ):
        """
        📝 רישום כניסה לעסקה
        
        Args:
            trade_id: מזהה ייחודי לעסקה
            symbol: סימבול
            direction: "long" or "short"
            entry_price: מחיר כניסה
            quantity: כמות
            leverage: ממונה
            initial_sl: SL ראשוני
            initial_tp: TP ראשוני
            atr: ATR בזמן כניסה
            quality_score: ציון איכות (אופציונלי)
            combo_used: קומבו ששימש (אופציונלי)
            market_regime: מצב שוק (אופציונלי)
            tags: תגיות (אופציונלי)
            notes: הערות (אופציונלי)
        """
        entry = TradeJournalEntry(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            entry_time=datetime.now().timestamp(),
            exit_time=None,
            entry_price=entry_price,
            exit_price=None,
            quantity=quantity,
            leverage=leverage,
            initial_sl=initial_sl,
            initial_tp=initial_tp,
            final_sl=None,
            final_tp=None,
            pnl_usd=None,
            pnl_pct=None,
            outcome=None,
            exit_reason=None,
            atr=atr,
            market_regime=market_regime,
            quality_score=quality_score,
            combo_used=combo_used,
            tags=tags or [],
            notes=notes
        )
        
        self.trades[trade_id] = entry
        self._save_journal()
        
        logger.info(f"📝 Recorded entry: {trade_id} - {symbol} {direction} @ {entry_price}")
    
    def record_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: ExitReason,
        final_sl: Optional[float] = None,
        final_tp: Optional[float] = None,
        notes: str = ""
    ):
        """
        📝 רישום יציאה מעסקה
        
        Args:
            trade_id: מזהה העסקה
            exit_price: מחיר יציאה
            exit_reason: סיבת יציאה
            final_sl: SL סופי (אם שונה)
            final_tp: TP סופי (אם שונה)
            notes: הערות נוספות
        """
        if trade_id not in self.trades:
            logger.warning(f"Trade {trade_id} not found in journal")
            return
        
        trade = self.trades[trade_id]
        trade.exit_time = datetime.now().timestamp()
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        
        if final_sl:
            trade.final_sl = final_sl
        if final_tp:
            trade.final_tp = final_tp
        
        # חישוב PnL
        if trade.direction.lower() == "long":
            pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:
            pnl_pct = (trade.entry_price - exit_price) / trade.entry_price
        
        trade.pnl_pct = pnl_pct
        # FIX: Don't multiply by leverage - pnl_pct already includes price move
        trade.pnl_usd = pnl_pct * (trade.quantity * trade.entry_price)
        
        # קביעת תוצאה
        if pnl_pct > 0.001:  # >0.1%
            trade.outcome = TradeOutcome.WIN
        elif pnl_pct < -0.001:  # <-0.1%
            trade.outcome = TradeOutcome.LOSS
        else:
            trade.outcome = TradeOutcome.BREAKEVEN
        
        if notes:
            trade.notes += f" | Exit: {notes}"
        
        self._save_journal()
        
        logger.info(
            f"📝 Recorded exit: {trade_id} - {trade.outcome.value} "
            f"PnL: ${trade.pnl_usd:.2f} ({pnl_pct*100:.2f}%)"
        )
    
    def update_trade(
        self,
        trade_id: str,
        updates: Dict[str, Any]
    ):
        """
        📝 עדכון פרטי עסקה
        
        Args:
            trade_id: מזהה העסקה
            updates: dictionary של עדכונים
        """
        if trade_id not in self.trades:
            logger.warning(f"Trade {trade_id} not found")
            return
        
        trade = self.trades[trade_id]
        for key, value in updates.items():
            if hasattr(trade, key):
                setattr(trade, key, value)
        
        self._save_journal()
        logger.debug(f"📝 Updated trade {trade_id}: {list(updates.keys())}")
    
    def get_closed_trades(
        self,
        days_back: Optional[int] = None,
        symbol: Optional[str] = None
    ) -> List[TradeJournalEntry]:
        """
        מחזיר עסקאות סגורות
        
        Args:
            days_back: מספר ימים אחורה (None = הכל)
            symbol: סינון לפי סימבול (None = הכל)
        
        Returns:
            רשימת עסקאות סגורות
        """
        closed_trades = [t for t in self.trades.values() if t.exit_time is not None]
        
        if days_back:
            cutoff = (datetime.now() - timedelta(days=days_back)).timestamp()
            closed_trades = [t for t in closed_trades if t.entry_time >= cutoff]
        
        if symbol:
            closed_trades = [t for t in closed_trades if t.symbol == symbol]
        
        return closed_trades
    
    def calculate_performance(
        self,
        days_back: Optional[int] = None,
        symbol: Optional[str] = None
    ) -> PerformanceMetrics:
        """
        📊 חישוב מדדי ביצועים
        
        Args:
            days_back: מספר ימים אחורה
            symbol: סינון לפי סימבול
        
        Returns:
            PerformanceMetrics
        """
        trades = self.get_closed_trades(days_back, symbol)
        
        if not trades:
            return PerformanceMetrics(
                total_trades=0, winning_trades=0, losing_trades=0, breakeven_trades=0,
                win_rate=0, avg_win=0, avg_loss=0, profit_factor=0, sharpe_ratio=0,
                max_drawdown=0, total_pnl=0, largest_win=0, largest_loss=0,
                avg_hold_time=0, avg_leverage=0
            )
        
        # בסיסי
        wins = [t for t in trades if t.outcome == TradeOutcome.WIN]
        losses = [t for t in trades if t.outcome == TradeOutcome.LOSS]
        breakevens = [t for t in trades if t.outcome == TradeOutcome.BREAKEVEN]
        
        # Win Rate
        win_rate = len(wins) / len(trades) if trades else 0
        
        # Average Win/Loss
        avg_win = statistics.mean([t.pnl_usd for t in wins]) if wins else 0
        avg_loss = abs(statistics.mean([t.pnl_usd for t in losses])) if losses else 0
        
        # Profit Factor
        total_wins = sum([t.pnl_usd for t in wins])
        total_losses = abs(sum([t.pnl_usd for t in losses]))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Total PnL
        total_pnl = sum([t.pnl_usd for t in trades])
        
        # Largest Win/Loss
        largest_win = max([t.pnl_usd for t in trades]) if trades else 0
        largest_loss = min([t.pnl_usd for t in trades]) if trades else 0
        
        # Sharpe Ratio (simplified - assumes daily returns)
        if len(trades) > 1:
            returns = [t.pnl_pct for t in trades]
            avg_return = statistics.mean(returns)
            std_return = statistics.stdev(returns)
            sharpe_ratio = avg_return / std_return if std_return > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Max Drawdown
        cumulative_pnl = []
        running_total = 0
        for trade in sorted(trades, key=lambda t: t.entry_time):
            running_total += trade.pnl_usd
            cumulative_pnl.append(running_total)
        
        max_drawdown = 0
        peak = cumulative_pnl[0] if cumulative_pnl else 0
        for value in cumulative_pnl:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Average Hold Time
        hold_times = [
            (t.exit_time - t.entry_time) / 3600  # to hours
            for t in trades if t.exit_time
        ]
        avg_hold_time = statistics.mean(hold_times) if hold_times else 0
        
        # Average Leverage
        avg_leverage = statistics.mean([t.leverage for t in trades])
        
        return PerformanceMetrics(
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            breakeven_trades=len(breakevens),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            total_pnl=total_pnl,
            largest_win=largest_win,
            largest_loss=largest_loss,
            avg_hold_time=avg_hold_time,
            avg_leverage=avg_leverage
        )
    
    def generate_weekly_report(self) -> str:
        """
        📊 יצירת דוח שבועי
        
        Returns:
            דוח טקסט
        """
        metrics = self.calculate_performance(days_back=7)
        
        report = f"""
📊 WEEKLY TRADING REPORT
========================

🎯 Performance Summary (Last 7 Days):
   Total Trades: {metrics.total_trades}
   Win Rate: {metrics.win_rate*100:.1f}% ({metrics.winning_trades}W / {metrics.losing_trades}L / {metrics.breakeven_trades}BE)
   
💰 P&L:
   Total PnL: ${metrics.total_pnl:.2f}
   Avg Win: ${metrics.avg_win:.2f}
   Avg Loss: ${metrics.avg_loss:.2f}
   Profit Factor: {metrics.profit_factor:.2f}
   
📈 Risk Metrics:
   Largest Win: ${metrics.largest_win:.2f}
   Largest Loss: ${metrics.largest_loss:.2f}
   Max Drawdown: {metrics.max_drawdown*100:.1f}%
   Sharpe Ratio: {metrics.sharpe_ratio:.2f}
   
⏱️ Trade Stats:
   Avg Hold Time: {metrics.avg_hold_time:.1f} hours
   Avg Leverage: {metrics.avg_leverage:.1f}x

========================
"""
        return report
    
    def identify_patterns(self, days_back: int = 30) -> Dict[str, Any]:
        """
        🔍 זיהוי דפוסים בביצועים
        
        Args:
            days_back: מספר ימים לניתוח
        
        Returns:
            דפוסים מזוהים
        """
        trades = self.get_closed_trades(days_back=days_back)
        
        if not trades:
            return {"error": "No trades to analyze"}
        
        # ניתוח לפי סימבול
        symbol_performance = {}
        for trade in trades:
            if trade.symbol not in symbol_performance:
                symbol_performance[trade.symbol] = {'wins': 0, 'losses': 0, 'pnl': 0}
            
            if trade.outcome == TradeOutcome.WIN:
                symbol_performance[trade.symbol]['wins'] += 1
            elif trade.outcome == TradeOutcome.LOSS:
                symbol_performance[trade.symbol]['losses'] += 1
            
            symbol_performance[trade.symbol]['pnl'] += trade.pnl_usd
        
        # ניתוח לפי כיוון
        long_trades = [t for t in trades if t.direction.lower() == 'long']
        short_trades = [t for t in trades if t.direction.lower() == 'short']
        
        long_win_rate = len([t for t in long_trades if t.outcome == TradeOutcome.WIN]) / len(long_trades) if long_trades else 0
        short_win_rate = len([t for t in short_trades if t.outcome == TradeOutcome.WIN]) / len(short_trades) if short_trades else 0
        
        # ניתוח לפי combo
        combo_performance = {}
        for trade in trades:
            if trade.combo_used:
                if trade.combo_used not in combo_performance:
                    combo_performance[trade.combo_used] = {'wins': 0, 'total': 0}
                
                combo_performance[trade.combo_used]['total'] += 1
                if trade.outcome == TradeOutcome.WIN:
                    combo_performance[trade.combo_used]['wins'] += 1
        
        return {
            'symbol_performance': symbol_performance,
            'long_win_rate': long_win_rate,
            'short_win_rate': short_win_rate,
            'combo_performance': combo_performance,
            'total_trades_analyzed': len(trades)
        }


__all__ = ["TradingJournal", "TradeJournalEntry", "PerformanceMetrics", "TradeOutcome", "ExitReason"]
