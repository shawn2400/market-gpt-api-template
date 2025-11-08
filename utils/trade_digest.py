"""
Trade Digest System - Consolidated Trade Reports
=================================================
Instead of sending individual messages for each trade,
batch them into a single comprehensive report.

Features:
- סיכום PNL כולל
- רשימת כל הטריידים עם פרטים
- Win Rate calculation
- אזהרות על trades ללא הגנה
- המלצות לשיפור
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import time

logger = logging.getLogger("trade_digest")


class TradeDigest:
    """
    Batches trade notifications into consolidated reports
    """
    
    def __init__(self, window_seconds: int = 300):
        """
        Args:
            window_seconds: Time window for batching trades (default 5 minutes)
        """
        self.window_seconds = window_seconds
        self.trades: List[Dict[str, Any]] = []
        self.last_report_time = time.time()
    
    def add_trade(self, trade_data: Dict[str, Any]):
        """
        Add a trade to the digest
        
        Expected trade_data keys:
        - symbol
        - side (LONG/SHORT/BUY/SELL)
        - entry_price
        - exit_price (optional)
        - qty
        - pnl_usdt
        - pnl_pct
        - duration_sec
        - has_protection (True/False)
        - timestamp
        """
        self.trades.append({
            **trade_data,
            'added_at': time.time()
        })
    
    def should_send_report(self) -> bool:
        """Check if it's time to send a report"""
        if not self.trades:
            return False
        
        time_since_last = time.time() - self.last_report_time
        return time_since_last >= self.window_seconds
    
    def generate_report(self) -> Optional[str]:
        """
        Generate consolidated report in Hebrew + English
        
        Returns:
            HTML formatted report for Telegram
        """
        if not self.trades:
            return None
        
        total_pnl = sum(t.get('pnl_usdt', 0) for t in self.trades)
        winners = [t for t in self.trades if t.get('pnl_usdt', 0) > 0]
        losers = [t for t in self.trades if t.get('pnl_usdt', 0) < 0]
        breakeven = [t for t in self.trades if t.get('pnl_usdt', 0) == 0]
        
        win_rate = (len(winners) / len(self.trades) * 100) if self.trades else 0
        
        unprotected = [t for t in self.trades if not t.get('has_protection', True)]
        
        start_time = datetime.fromtimestamp(
            min(t.get('timestamp', time.time()) for t in self.trades),
            tz=timezone.utc
        )
        end_time = datetime.fromtimestamp(
            max(t.get('timestamp', time.time()) for t in self.trades),
            tz=timezone.utc
        )
        
        pnl_emoji = "🟢" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚪"
        pnl_sign = "+" if total_pnl > 0 else ""
        
        report_lines = [
            f"📊 <b>סיכום טריידים - Trade Summary</b>",
            f"🕒 {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}",
            "",
            f"{pnl_emoji} <b>סה\"כ PNL: {pnl_sign}{total_pnl:.2f} USDT</b>",
            f"📈 Win Rate: {win_rate:.1f}% ({len(winners)}/{len(self.trades)})",
            f"✅ Wins: {len(winners)} | ❌ Losses: {len(losers)} | ⚪ BE: {len(breakeven)}",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        for idx, trade in enumerate(self.trades, 1):
            symbol = trade.get('symbol', 'UNKNOWN')
            side = trade.get('side', 'UNKNOWN')
            entry_price = trade.get('entry_price', 0)
            exit_price = trade.get('exit_price', 0)
            pnl_usdt = trade.get('pnl_usdt', 0)
            pnl_pct = trade.get('pnl_pct', 0)
            duration_sec = trade.get('duration_sec', 0)
            has_protection = trade.get('has_protection', True)
            
            duration_str = self._format_duration(duration_sec)
            
            pnl_emoji_trade = "✅" if pnl_usdt > 0 else "❌" if pnl_usdt < 0 else "⚪"
            pnl_sign_trade = "+" if pnl_usdt > 0 else ""
            
            protection_status = ""
            if not has_protection:
                protection_status = "\n   ⚠️ <b>נסגר ללא SL/TP - No Protection!</b>"
            
            report_lines.extend([
                f"{idx}️⃣ <b>{symbol}</b> {side}",
                f"   Entry: {entry_price:.6g} → Exit: {exit_price:.6g}" if exit_price else f"   Entry: {entry_price:.6g}",
                f"   {pnl_emoji_trade} PNL: {pnl_sign_trade}{pnl_usdt:.2f} USDT ({pnl_sign_trade}{pnl_pct:.2f}%)",
                f"   ⏱️ Duration: {duration_str}",
                protection_status,
                ""
            ])
        
        if unprotected:
            report_lines.extend([
                "━━━━━━━━━━━━━━━━━━━━",
                "⚠️ <b>אזהרות - Warnings</b>",
                f"🚨 {len(unprotected)} trades נסגרו ללא הגנת SL/TP!",
                "💡 Emergency Protection מופעל",
                ""
            ])
        
        recommendations = self._generate_recommendations(
            total_pnl=total_pnl,
            win_rate=win_rate,
            unprotected_count=len(unprotected)
        )
        
        if recommendations:
            report_lines.extend([
                "━━━━━━━━━━━━━━━━━━━━",
                "💡 <b>המלצות - Recommendations</b>",
                *recommendations
            ])
        
        return "\n".join(report_lines)
    
    def _format_duration(self, duration_sec: float) -> str:
        """Format duration in Hebrew + English"""
        if duration_sec < 60:
            return f"{duration_sec:.0f} שניות / {duration_sec:.0f}s"
        elif duration_sec < 3600:
            minutes = duration_sec / 60
            return f"{minutes:.1f} דקות / {minutes:.1f}min"
        else:
            hours = duration_sec / 3600
            return f"{hours:.1f} שעות / {hours:.1f}h"
    
    def _generate_recommendations(
        self, 
        total_pnl: float, 
        win_rate: float,
        unprotected_count: int
    ) -> List[str]:
        """Generate actionable recommendations"""
        recs = []
        
        if unprotected_count > 0:
            recs.append("🔴 בדיקת SL/TP Protection - Critical!")
            recs.append("🔴 Circuit Breaker check required")
        
        if win_rate < 40:
            recs.append("📉 Win Rate נמוך - שקול הפסקה זמנית")
            recs.append("📉 Low Win Rate - consider pause")
        
        if total_pnl < -20:
            recs.append("💰 הפסד משמעותי - בדוק פרמטרים")
            recs.append("💰 Significant loss - review parameters")
        
        if not recs:
            if win_rate > 60 and total_pnl > 0:
                recs.append("✅ ביצועים טובים - המשך!")
                recs.append("✅ Good performance - continue!")
        
        return recs
    
    def clear_trades(self):
        """Clear trades after sending report"""
        self.trades = []
        self.last_report_time = time.time()


_digest_instance: Optional[TradeDigest] = None

def get_trade_digest() -> TradeDigest:
    """Get singleton instance"""
    global _digest_instance
    if _digest_instance is None:
        _digest_instance = TradeDigest(window_seconds=300)  # 5 minutes
    return _digest_instance
