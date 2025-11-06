# utils/telegram_daily_report.py
"""
Daily Trading Report for Telegram.
Sends comprehensive daily summary with PnL, Win Rate, Best/Worst trades.
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import json

log = logging.getLogger(__name__)


class TelegramDailyReport:
    """Generates and sends daily trading performance reports."""

    def __init__(self, telegram_notifier=None):
        """
        Args:
            telegram_notifier: Module with send_message function
        """
        self.notifier = telegram_notifier
        self.trades_log_path = Path(os.getenv("PNL_HEARTBEAT_LOG_PATH", "static/cache/trades_log.json"))

    def load_today_trades(self) -> List[Dict[str, Any]]:
        """Load all trades from today."""
        try:
            if not self.trades_log_path.exists():
                return []

            with open(self.trades_log_path, "r") as f:
                all_trades = json.load(f)

            # Filter today's trades
            today = datetime.utcnow().date()
            today_trades = []
            for trade in all_trades:
                trade_time = trade.get("close_time") or trade.get("open_time")
                if not trade_time:
                    continue
                try:
                    trade_date = datetime.fromisoformat(trade_time.replace("Z", "+00:00")).date()
                    if trade_date == today:
                        today_trades.append(trade)
                except Exception:
                    continue

            return today_trades
        except Exception as e:
            log.error(f"[DailyReport] Failed to load trades: {e}")
            return []

    def calculate_metrics(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate daily trading metrics."""
        if not trades:
            return {
                "total_trades": 0,
                "total_pnl": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "best_trade": None,
                "worst_trade": None,
            }

        total_pnl = 0.0
        wins = []
        losses = []

        for trade in trades:
            pnl = float(trade.get("pnl", 0))
            total_pnl += pnl
            if pnl > 0:
                wins.append(trade)
            elif pnl < 0:
                losses.append(trade)

        # Best and worst
        best_trade = max(trades, key=lambda t: float(t.get("pnl", 0)))
        worst_trade = min(trades, key=lambda t: float(t.get("pnl", 0)))

        return {
            "total_trades": len(trades),
            "total_pnl": total_pnl,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
            "avg_win": (sum(float(t.get("pnl", 0)) for t in wins) / len(wins)) if wins else 0.0,
            "avg_loss": (sum(float(t.get("pnl", 0)) for t in losses) / len(losses)) if losses else 0.0,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
        }

    def format_report(self, metrics: Dict[str, Any]) -> str:
        """Format metrics into Telegram message."""
        if metrics["total_trades"] == 0:
            return "📊 <b>Daily Trading Report</b>\n\n❌ No trades today."

        pnl = metrics["total_pnl"]
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        pnl_sign = "+" if pnl >= 0 else ""

        report = f"""📊 <b>Daily Trading Report</b>
📅 {datetime.utcnow().strftime('%Y-%m-%d')}

━━━━━━━━━━━━━━━━━━━━━
{pnl_emoji} <b>PnL: {pnl_sign}{pnl:.2f} USDT</b>
━━━━━━━━━━━━━━━━━━━━━

📈 <b>Statistics:</b>
• Total Trades: {metrics['total_trades']}
• Wins: {metrics['win_count']} ({metrics['win_rate']:.1f}%)
• Losses: {metrics['loss_count']}
• Avg Win: +{metrics['avg_win']:.2f} USDT
• Avg Loss: {metrics['avg_loss']:.2f} USDT

"""

        # Best trade
        if metrics["best_trade"]:
            best = metrics["best_trade"]
            report += f"""🏆 <b>Best Trade:</b>
• Symbol: {best.get('symbol', 'N/A')}
• PnL: +{float(best.get('pnl', 0)):.2f} USDT
• Side: {best.get('side', 'N/A')}

"""

        # Worst trade
        if metrics["worst_trade"]:
            worst = metrics["worst_trade"]
            report += f"""💀 <b>Worst Trade:</b>
• Symbol: {worst.get('symbol', 'N/A')}
• PnL: {float(worst.get('pnl', 0)):.2f} USDT
• Side: {worst.get('side', 'N/A')}

"""

        report += "━━━━━━━━━━━━━━━━━━━━━\n"
        report += "🤖 AlgoGPT MetaBrain v8.0"

        return report

    async def send_daily_report(self) -> bool:
        """Generate and send daily trading report via Telegram."""
        try:
            trades = self.load_today_trades()
            metrics = self.calculate_metrics(trades)
            message = self.format_report(metrics)

            if self.notifier:
                await self.notifier.send_message(message)
                log.info(f"[DailyReport] ✅ Sent report ({metrics['total_trades']} trades, PnL: {metrics['total_pnl']:.2f})")
                return True
            else:
                log.warning("[DailyReport] No telegram notifier configured")
                return False

        except Exception as e:
            log.error(f"[DailyReport] Failed to send report: {e}")
            return False


def get_daily_report_instance():
    """Get singleton instance of daily report generator."""
    try:
        from utils import telegram_notifier

        return TelegramDailyReport(telegram_notifier)
    except Exception as e:
        log.warning(f"[DailyReport] Failed to initialize: {e}")
        return None
