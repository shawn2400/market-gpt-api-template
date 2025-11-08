#!/usr/bin/env python3
"""
Enhanced Trade Notifications - Detailed Telegram Trade Messages
==============================================================
Professional Hebrew + English trade notifications with COMPLETE details:

On Trade Open:
- Strategy, Order Type (LIMIT/MARKET)
- Investment reasoning, Leverage reasoning
- SL/TP levels with expected $
- Expected profit, Duration estimate
- Trade Score, Auto-Flip status
- REAL-TIME PNL tracking

Format: 70% עברית + 30% English
Part of MetaBrain v9.1 - Professional Trader Experience
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger("algogpt.enhanced_notifications")


class EnhancedTradeNotifier:
    """
    Generates professional Telegram trade notifications.
    
    All messages include:
    - Complete trade details
    - AI reasoning for decisions
    - Expected outcomes
    - Real-time PNL (for open trades)
    - Professional Unicode formatting
    """
    
    def __init__(self):
        self.logger = logger
    
    def format_trade_open_notification(
        self,
        trade_data: Dict[str, Any],
        precision_sizing: Optional[Any] = None,  # PrecisionSizing object
        strategy_consensus: Optional[Any] = None,  # StrategyConsensus object
        auto_flip: bool = False,
        flip_reason: Optional[str] = None
    ) -> str:
        """
        Format comprehensive trade open notification.
        
        Args:
            trade_data: Trade details (symbol, side, entry, SL, TP, etc.)
            precision_sizing: PrecisionSizing result with leverage/investment reasoning
            strategy_consensus: StrategyConsensus with strategy selection reasoning
            auto_flip: Whether auto-flip occurred
            flip_reason: Reason for flip if applicable
        
        Returns:
            Formatted HTML message
        """
        # Extract data
        symbol = trade_data.get("symbol", "UNKNOWN")
        side = trade_data.get("side", "BUY")
        strategy = trade_data.get("strategy", "UNKNOWN")
        order_type = trade_data.get("order_type", "MARKET")
        
        entry = trade_data.get("entry", 0)
        leverage = trade_data.get("leverage", 1)
        investment_usd = trade_data.get("investment_usd", 0)
        position_size = investment_usd * leverage if investment_usd else 0
        quantity = trade_data.get("qty", 0)
        
        # SL/TP data
        sl_price = trade_data.get("sl", {}).get("stopPrice", 0) if isinstance(trade_data.get("sl"), dict) else 0
        tp_levels = trade_data.get("tp", [])
        
        # Metadata
        score = trade_data.get("score", 0)
        expected_profit = trade_data.get("expected_profit_usd", 0)
        expected_duration = trade_data.get("expected_duration_hours", 0)
        rr_ratio = trade_data.get("rr", 0)
        
        # Wallet %
        wallet_balance = trade_data.get("wallet_balance", 0)
        wallet_pct = (investment_usd / wallet_balance * 100) if wallet_balance > 0 else 0
        
        # Build message
        msg = f"""🎯 <b>NEW TRADE OPENED</b>

━━━━━━━━━━━━━━━━━━━━
📊 <b>TRADE DETAILS</b>
━━━━━━━━━━━━━━━━━━━━

<b>Symbol:</b> {symbol}
<b>Strategy:</b> {self._translate_strategy(strategy)}
<b>Side:</b> {self._format_side(side)}
<b>Order Type:</b> {order_type}
"""
        
        # Auto-Flip notice
        if auto_flip and flip_reason:
            msg += f"""
🔄 <b>AUTO-FLIP EXECUTED</b>
{flip_reason}
"""
        
        msg += f"""
━━━━━━━━━━━━━━━━━━━━
💰 <b>POSITION DETAILS</b>
━━━━━━━━━━━━━━━━━━━━

<b>Entry:</b> {entry:.6f} USDT
<b>Investment:</b> ${investment_usd:.2f} ({wallet_pct:.1f}% of wallet)
<b>Leverage:</b> {leverage:.2f}x
<b>Position Size:</b> ${position_size:.2f}
<b>Quantity:</b> {quantity:.4f} {symbol.replace('USDT', '')}
"""
        
        # SL/TP section
        msg += f"""
━━━━━━━━━━━━━━━━━━━━
🎯 <b>TARGETS & PROTECTION</b>
━━━━━━━━━━━━━━━━━━━━
"""
        
        if sl_price > 0:
            sl_pct = ((sl_price - entry) / entry * 100) if entry > 0 else 0
            sl_loss = abs(position_size * sl_pct / 100) if sl_pct < 0 else 0
            msg += f"""
🛡️ <b>SL:</b> {sl_price:.6f} USDT ({sl_pct:+.2f}%) 
   Max Loss: -${sl_loss:.2f}
"""
        
        if tp_levels:
            for i, tp in enumerate(tp_levels[:4], 1):
                tp_price = tp.get("price", 0)
                tp_pct_position = tp.get("pct", 0)
                
                if tp_price > 0:
                    tp_pct_move = ((tp_price - entry) / entry * 100) if entry > 0 else 0
                    tp_profit = abs(position_size * tp_pct_move / 100 * tp_pct_position / 100)
                    
                    msg += f"""🎯 <b>TP{i}:</b> {tp_price:.6f} USDT ({tp_pct_move:+.2f}%) - {tp_pct_position:.0f}%
   Profit: +${tp_profit:.2f}
"""
        
        # Expectations
        msg += f"""
━━━━━━━━━━━━━━━━━━━━
📈 <b>EXPECTATIONS</b>
━━━━━━━━━━━━━━━━━━━━

<b>Expected Profit:</b> +${expected_profit:.2f}
<b>Expected Duration:</b> {self._format_duration(expected_duration)}
<b>Trade Score:</b> {score:.1f}/10
<b>Risk/Reward:</b> {rr_ratio:.2f}
"""
        
        # AI Reasoning
        msg += f"""
━━━━━━━━━━━━━━━━━━━━
🧠 <b>AI REASONING</b>
━━━━━━━━━━━━━━━━━━━━
"""
        
        # Investment reasoning
        if precision_sizing:
            inv_reason = precision_sizing.reasoning if hasattr(precision_sizing, 'reasoning') else "N/A"
            msg += f"""
<b>Why this investment?</b>
{inv_reason}
"""
        
        # Strategy reasoning
        if strategy_consensus:
            strat_reason = strategy_consensus.reasoning if hasattr(strategy_consensus, 'reasoning') else "N/A"
            votes = getattr(strategy_consensus, 'votes_approve', 0)
            total = getattr(strategy_consensus, 'total_votes', 0)
            msg += f"""
<b>Why this strategy?</b>
AI Consensus: {votes}/{total} brains approved
{strat_reason[:200]}
"""
        
        # Market conditions
        regime = trade_data.get("market_regime", "UNKNOWN")
        volatility = trade_data.get("volatility", "medium")
        
        msg += f"""
<b>Market Regime:</b> {regime}
<b>Volatility:</b> {volatility}
"""
        
        # Trade ID
        ticket_id = trade_data.get("ticket_id", "N/A")
        msg += f"""
━━━━━━━━━━━━━━━━━━━━
✅ <b>Trade ID:</b> #{ticket_id}
"""
        
        return msg
    
    def format_trade_update_notification(
        self,
        symbol: str,
        side: str,
        entry: float,
        current_price: float,
        unrealized_pnl_usd: float,
        unrealized_pnl_pct: float,
        position_size: float,
        leverage: float,
        sl_price: Optional[float] = None,
        tp_hit: Optional[str] = None,
        duration_seconds: int = 0
    ) -> str:
        """
        Format trade update notification with real-time PNL.
        
        Used for periodic updates on open positions.
        """
        pnl_emoji = "🟢" if unrealized_pnl_usd > 0 else "🔴" if unrealized_pnl_usd < 0 else "⚖️"
        pnl_status = "PROFIT" if unrealized_pnl_usd > 0 else "LOSS" if unrealized_pnl_usd < 0 else "BREAKEVEN"
        
        duration_str = self._format_duration_seconds(duration_seconds)
        
        msg = f"""📊 <b>TRADE UPDATE</b> {pnl_emoji}

<b>Symbol:</b> {symbol} {self._format_side(side)}
<b>Duration:</b> {duration_str}

━━━━━━━━━━━━━━━━━━━━
💰 <b>CURRENT PNL</b>
━━━━━━━━━━━━━━━━━━━━

<b>Entry:</b> {entry:.6f} USDT
<b>Current:</b> {current_price:.6f} USDT
<b>Move:</b> {unrealized_pnl_pct:+.2f}%

<b>Position Size:</b> ${position_size:.2f}
<b>Leverage:</b> {leverage:.2f}x

<b>Unrealized PNL:</b> {pnl_emoji} {pnl_status}
<b>P&L Amount:</b> ${unrealized_pnl_usd:+.2f}
<b>ROI:</b> {unrealized_pnl_pct:+.2f}%
"""
        
        if tp_hit:
            msg += f"""
✅ <b>TP Hit:</b> {tp_hit}
"""
        
        if sl_price:
            dist_to_sl_pct = ((current_price - sl_price) / current_price * 100) if current_price > 0 else 0
            msg += f"""
🛡️ <b>SL:</b> {sl_price:.6f} ({dist_to_sl_pct:+.2f}% away)
"""
        
        return msg
    
    def _translate_strategy(self, strategy: str) -> str:
        """Translate strategy name to Hebrew + English"""
        translations = {
            "grid": "GRID - רשת מסחר",
            "mean_reversion": "Mean-Reversion - חזרה לממוצע",
            "scalping": "Scalping - סקלפינג מהיר",
            "momentum": "Momentum - מומנטום",
            "range_bounce": "Range Bounce - ניתור טווח",
            "breakout": "Breakout - פריצה"
        }
        return translations.get(strategy.lower(), strategy.upper())
    
    def _format_side(self, side: str) -> str:
        """Format side with emoji"""
        if side.upper() in ("BUY", "LONG"):
            return "LONG 🟢"
        elif side.upper() in ("SELL", "SHORT"):
            return "SHORT 🔴"
        return side
    
    def _format_duration(self, hours: float) -> str:
        """Format duration estimate"""
        if hours < 1:
            mins = int(hours * 60)
            return f"{mins} דקות"
        elif hours < 24:
            return f"{hours:.1f} שעות"
        else:
            days = hours / 24
            return f"{days:.1f} ימים"
    
    def _format_duration_seconds(self, seconds: int) -> str:
        """Format duration from seconds"""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            mins = seconds // 60
            secs = seconds % 60
            return f"{mins}m {secs}s"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{hours}h {mins}m"


# Singleton instance
_notifier: Optional[EnhancedTradeNotifier] = None


def get_enhanced_notifier() -> EnhancedTradeNotifier:
    """Get or create singleton enhanced notifier"""
    global _notifier
    if _notifier is None:
        _notifier = EnhancedTradeNotifier()
    return _notifier


def format_trade_open(
    trade_data: Dict[str, Any],
    precision_sizing: Optional[Any] = None,
    strategy_consensus: Optional[Any] = None,
    auto_flip: bool = False,
    flip_reason: Optional[str] = None
) -> str:
    """
    Convenience function to format trade open notification.
    
    Returns HTML-formatted message for Telegram.
    """
    notifier = get_enhanced_notifier()
    return notifier.format_trade_open_notification(
        trade_data, precision_sizing, strategy_consensus,
        auto_flip, flip_reason
    )


def format_trade_update(
    symbol: str,
    side: str,
    entry: float,
    current_price: float,
    unrealized_pnl_usd: float,
    unrealized_pnl_pct: float,
    position_size: float,
    leverage: float,
    sl_price: Optional[float] = None,
    tp_hit: Optional[str] = None,
    duration_seconds: int = 0
) -> str:
    """
    Convenience function to format trade update notification with PNL.
    
    Returns HTML-formatted message for Telegram.
    """
    notifier = get_enhanced_notifier()
    return notifier.format_trade_update_notification(
        symbol, side, entry, current_price,
        unrealized_pnl_usd, unrealized_pnl_pct,
        position_size, leverage, sl_price, tp_hit, duration_seconds
    )
