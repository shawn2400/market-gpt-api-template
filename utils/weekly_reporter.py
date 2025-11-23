# -*- coding: utf-8 -*-
"""
Priority 4: Weekly Reports System - Automated weekly trading summary reports.
Dynamic auto-activation on Sundays at 00:00.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from contextlib import suppress

logger = logging.getLogger(__name__)

# Dynamic config with fallbacks
ENABLE_WEEKLY_REPORTS = os.getenv("ENABLE_WEEKLY_REPORTS", "1") == "1"
REPORT_DAY = os.getenv("REPORT_DAY", "0")  # 0 = Sunday
REPORT_TIME = os.getenv("REPORT_TIME", "00:00")
TELEGRAM_DIGEST_ENABLE = os.getenv("TELEGRAM_DIGEST_ENABLE", "1") == "1"
EMAIL_REPORTS_ENABLE = os.getenv("EMAIL_REPORTS_ENABLE", "0") == "1"


class WeeklyReporter:
    """Automated weekly trading summary report generator."""
    
    def __init__(self):
        self.enabled = ENABLE_WEEKLY_REPORTS
        self.last_report_ts = 0.0
        self.report_cache = {}
    
    def should_generate_report(self, current_ts: float = None) -> bool:
        """Check if weekly report should be generated (dynamic activation)."""
        if not self.enabled:
            return False
        
        if current_ts is None:
            from time import time
            current_ts = time()
        
        # Auto-activate on Sundays at report time
        dt = datetime.fromtimestamp(current_ts)
        is_sunday = dt.weekday() == 6
        
        # Check if report already generated today
        time_since_last = current_ts - self.last_report_ts
        already_generated = time_since_last < 86400  # 24 hours
        
        return is_sunday and not already_generated
    
    def calculate_weekly_stats(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate weekly performance statistics from trade list."""
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl_per_trade": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "sharpe_ratio": 0.0,
                "symbols_traded": []
            }
        
        pnls = [t.get("pnl", 0) for t in trades]
        winning_trades = len([p for p in pnls if p > 0])
        losing_trades = len([p for p in pnls if p < 0])
        total_trades = len(trades)
        
        total_pnl = sum(pnls)
        total_profit = sum([p for p in pnls if p > 0])
        total_loss = sum([p for p in pnls if p < 0])
        
        import numpy as np
        with suppress(Exception):
            sharpe = np.mean(pnls) / (np.std(pnls) + 1e-6) if len(pnls) > 1 else 0.0
        sharpe = 0.0
        
        symbols = list(set([t.get("symbol") for t in trades if t.get("symbol")]))
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(winning_trades / total_trades if total_trades > 0 else 0, 3),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_per_trade": round(total_pnl / total_trades if total_trades > 0 else 0, 2),
            "best_trade": round(max(pnls) if pnls else 0, 2),
            "worst_trade": round(min(pnls) if pnls else 0, 2),
            "total_profit": round(total_profit, 2),
            "total_loss": round(total_loss, 2),
            "sharpe_ratio": round(sharpe, 3),
            "symbols_traded": symbols[:10]  # Top 10
        }
    
    def format_telegram_report(self, stats: Dict[str, Any], period: str = "Weekly") -> str:
        """Format statistics as Telegram-friendly HTML message."""
        msg = f"""
📊 <b>{period} Trading Report</b>

<b>Performance Summary:</b>
• Total Trades: {stats['total_trades']}
• Winning: {stats['winning_trades']} ({stats['win_rate']*100:.1f}%)
• Losing: {stats['losing_trades']}
• Win/Loss Ratio: {stats['total_profit']:.2f} / {abs(stats['total_loss']):.2f}

<b>Profitability:</b>
• Total PNL: ${stats['total_pnl']:.2f}
• Avg PNL/Trade: ${stats['avg_pnl_per_trade']:.2f}
• Best Trade: ${stats['best_trade']:.2f}
• Worst Trade: ${stats['worst_trade']:.2f}
• Sharpe Ratio: {stats['sharpe_ratio']:.3f}

<b>Top Symbols:</b>
{', '.join(stats['symbols_traded']) if stats['symbols_traded'] else 'N/A'}

Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
"""
        return msg.strip()
    
    def format_email_report(self, stats: Dict[str, Any], period: str = "Weekly") -> Dict[str, str]:
        """Format statistics as HTML email body."""
        html = f"""
<html>
<head>
<style>
body {{ font-family: Arial, sans-serif; }}
.header {{ background-color: #1f2937; color: white; padding: 20px; text-align: center; }}
.stats {{ margin: 20px; }}
.stat-row {{ display: flex; justify-content: space-between; padding: 8px; border-bottom: 1px solid #e5e7eb; }}
.stat-label {{ font-weight: bold; }}
.positive {{ color: #10b981; }}
.negative {{ color: #ef4444; }}
</style>
</head>
<body>
<div class="header">
<h1>{period} Trading Report</h1>
</div>
<div class="stats">
<h2>Performance Summary</h2>
<div class="stat-row">
  <span class="stat-label">Total Trades:</span>
  <span>{stats['total_trades']}</span>
</div>
<div class="stat-row">
  <span class="stat-label">Win Rate:</span>
  <span class="positive">{stats['winning_trades']} ({stats['win_rate']*100:.1f}%)</span>
</div>
<div class="stat-row">
  <span class="stat-label">Total PNL:</span>
  <span class="{'positive' if stats['total_pnl'] > 0 else 'negative'}">${{stats['total_pnl']:.2f}}</span>
</div>
<div class="stat-row">
  <span class="stat-label">Best Trade:</span>
  <span class="positive">${{stats['best_trade']:.2f}}</span>
</div>
<div class="stat-row">
  <span class="stat-label">Worst Trade:</span>
  <span class="negative">${{stats['worst_trade']:.2f}}</span>
</div>
</div>
</body>
</html>
"""
        return {"html": html, "text": self.format_telegram_report(stats, period)}
    
    def generate_report(self, trades: List[Dict[str, Any]], 
                       telegram_callback=None, 
                       email_callback=None) -> Dict[str, Any]:
        """Generate and distribute weekly report."""
        stats = self.calculate_weekly_stats(trades)
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "period": "weekly",
            "stats": stats,
            "telegram_sent": False,
            "email_sent": False
        }
        
        # Send Telegram report (dynamic activation)
        if TELEGRAM_DIGEST_ENABLE and telegram_callback:
            with suppress(Exception):
                tg_msg = self.format_telegram_report(stats)
                telegram_callback(tg_msg)
                report["telegram_sent"] = True
                logger.info("✅ Weekly Telegram report sent")
        
        # Send Email report (dynamic activation)
        if EMAIL_REPORTS_ENABLE and email_callback:
            with suppress(Exception):
                email_data = self.format_email_report(stats)
                email_callback(email_data)
                report["email_sent"] = True
                logger.info("✅ Weekly email report sent")
        
        self.last_report_ts = datetime.utcnow().timestamp()
        self.report_cache = report
        
        return report
    
    def get_last_report(self) -> Optional[Dict[str, Any]]:
        """Get last generated report from cache."""
        return self.report_cache if self.report_cache else None


# Global singleton instance with dynamic auto-activation
_weekly_reporter = None


def get_weekly_reporter() -> WeeklyReporter:
    """Get or create global weekly reporter instance (singleton)."""
    global _weekly_reporter
    if _weekly_reporter is None:
        _weekly_reporter = WeeklyReporter()
        if ENABLE_WEEKLY_REPORTS:
            logger.info("✅ Weekly Reporter initialized (dynamic auto-activation enabled)")
        else:
            logger.info("ℹ️  Weekly Reporter disabled (ENABLE_WEEKLY_REPORTS=0)")
    return _weekly_reporter
