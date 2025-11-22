#!/usr/bin/env python3
# utils/enhanced_telegram_formatter.py
"""
Enhanced Telegram Formatter - Rich Messages with Scores, AI Status, and Detailed Summaries
========================================================================================
Creates comprehensive Telegram reports with:
- System health score (0-100)
- AI agents status and individual scores
- Trade summaries with profit predictions
- Expected ROI and time estimates
- TP hit success rates by percentage
- Color-coded emoji indicators
"""

import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("enhanced_telegram_formatter")

# ===================== AI BRAINS CONFIG =====================
AI_BRAINS = {
    "deepseek": {"emoji": "🧠", "name": "DeepSeek", "status": "unknown"},
    "grok": {"emoji": "⚡", "name": "Grok", "status": "unknown"},
    "claude": {"emoji": "🎯", "name": "Claude", "status": "unknown"},
    "qwen": {"emoji": "🌟", "name": "Qwen", "status": "unknown"},
    "gemini": {"emoji": "✨", "name": "Gemini", "status": "unknown"},
    "falcon": {"emoji": "🦅", "name": "Falcon", "status": "unknown"},
    "mixtral": {"emoji": "🎪", "name": "Mixtral", "status": "unknown"},
}

# ===================== HEALTH SCORE CALCULATION =====================
def calculate_system_score(
    active_positions: int = 0,
    total_pnl: float = 0.0,
    win_rate: float = 0.0,
    api_errors: int = 0,
    trades_executed: int = 0,
    leverage_avg: float = 1.0,
    protection_active: bool = True
) -> Dict[str, Any]:
    """
    Calculate comprehensive system health score (0-100)
    
    Factors:
    - Profitability: +40 max
    - Win rate: +20 max
    - Trades executed: +15 max
    - API health: +15 max
    - Protection status: +10 max
    """
    score = 0
    breakdown = {}
    
    # 1. Profitability score (0-40)
    if total_pnl > 100:
        prof_score = 40
    elif total_pnl > 50:
        prof_score = 30
    elif total_pnl > 0:
        prof_score = 15
    elif total_pnl > -50:
        prof_score = 5
    else:
        prof_score = 0
    score += prof_score
    breakdown["profitability"] = prof_score
    
    # 2. Win rate score (0-20)
    wr_score = min(20, (win_rate / 5))
    score += wr_score
    breakdown["win_rate"] = wr_score
    
    # 3. Trading activity score (0-15)
    activity_score = min(15, trades_executed * 2)
    score += activity_score
    breakdown["activity"] = activity_score
    
    # 4. API health score (0-15)
    api_score = max(0, 15 - (api_errors * 2))
    score += api_score
    breakdown["api_health"] = api_score
    
    # 5. Protection score (0-10)
    protection_score = 10 if protection_active else 0
    score += protection_score
    breakdown["protection"] = protection_score
    
    return {
        "total": min(100, score),
        "breakdown": breakdown,
        "emoji": _score_emoji(score)
    }

def _score_emoji(score: float) -> str:
    """Return emoji based on score"""
    if score >= 80:
        return "🟢"
    elif score >= 60:
        return "🟡"
    elif score >= 40:
        return "🟠"
    else:
        return "🔴"

# ===================== AI BRAIN STATUS =====================
def get_ai_brain_status(brain_name: str, is_active: bool, score: float = 0.0, error_msg: str = "") -> str:
    """Format single AI brain status line"""
    if brain_name not in AI_BRAINS:
        return ""
    
    brain = AI_BRAINS[brain_name]
    emoji = brain["emoji"]
    name = brain["name"]
    
    if is_active:
        status_indicator = "✅" if score > 0.5 else "⚠️"
        return f"{emoji} {status_indicator} {name}: {score:.1f}/10"
    else:
        if "insufficient" in error_msg.lower() or "402" in error_msg:
            return f"{emoji} ❌ {name}: No credits"
        elif "unavailable" in error_msg.lower():
            return f"{emoji} ❌ {name}: Unavailable"
        else:
            return f"{emoji} ⚫ {name}: Inactive"

def format_ai_brains_status(active_brains: List[str], brain_scores: Dict[str, float], error_msgs: Dict[str, str]) -> str:
    """Format all AI brains status"""
    lines = ["🧠 <b>AI Agents Status</b>"]
    
    for brain_name in AI_BRAINS.keys():
        is_active = brain_name in active_brains
        score = brain_scores.get(brain_name, 0.0)
        error = error_msgs.get(brain_name, "")
        status_line = get_ai_brain_status(brain_name, is_active, score, error)
        if status_line:
            lines.append(f"  {status_line}")
    
    return "\n".join(lines)

# ===================== TRADE SUMMARY =====================
def format_trade_summary(
    trades: List[Dict[str, Any]],
    open_positions: List[Dict[str, Any]] = None
) -> str:
    """
    Format comprehensive trade summary with:
    - Individual trade details (symbol, entry, exit, PNL, duration, TP times)
    - Profit metrics
    - Success rate per TP
    """
    if not trades and not open_positions:
        return "📊 <b>No trades</b>"
    
    lines = ["📊 <b>Trade Summary</b>"]
    
    total_pnl = 0.0
    total_pnl_pct = 0.0
    winners = 0
    losers = 0
    
    # Closed trades
    if trades:
        lines.append("\n<b>✅ Closed Trades</b>")
        for idx, trade in enumerate(trades, 1):
            symbol = trade.get("symbol", "?")
            side = trade.get("side", "?")
            entry = trade.get("entry_price", 0)
            exit_price = trade.get("exit_price", 0)
            pnl_usd = trade.get("pnl_usd", 0)
            pnl_pct = trade.get("pnl_pct", 0)
            duration_sec = trade.get("duration_sec", 0)
            leverage = trade.get("leverage", 1)
            entry_time = trade.get("entry_time", 0)
            exit_time = trade.get("exit_time", 0)
            exit_reason = trade.get("exit_reason", "unknown")
            tp_hit = trade.get("tp_hit", False)
            
            total_pnl += pnl_usd
            total_pnl_pct += pnl_pct
            
            if pnl_usd > 0:
                winners += 1
                emoji = "🟢"
            elif pnl_usd < 0:
                losers += 1
                emoji = "🔴"
            else:
                emoji = "⚪"
            
            # Duration formatting
            if duration_sec < 60:
                duration_str = f"{duration_sec:.0f}s"
            elif duration_sec < 3600:
                duration_str = f"{duration_sec/60:.1f}m"
            else:
                duration_str = f"{duration_sec/3600:.1f}h"
            
            # Exit reason emoji
            exit_emoji = "🎯" if tp_hit else "🛑" if "SL" in exit_reason else "❌"
            
            lines.append(
                f"{idx}. {symbol} {side} {emoji}\n"
                f"   💰 {entry:.6g} → {exit_price:.6g}\n"
                f"   📈 PNL: +{pnl_usd:.2f}$ ({pnl_pct:+.2f}%) | {leverage}x\n"
                f"   ⏱️ {duration_str} | {exit_emoji} {exit_reason}"
            )
    
    # Open positions
    if open_positions:
        lines.append("\n<b>📍 Open Positions</b>")
        for idx, pos in enumerate(open_positions, 1):
            symbol = pos.get("symbol", "?")
            side = pos.get("side", "?")
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", 0)
            pnl_pct = pos.get("pnl_pct", 0)
            leverage = pos.get("leverage", 1)
            time_open = pos.get("time_open", 0)
            sl_price = pos.get("sl_price")
            tp_prices = pos.get("tp_prices", [])
            
            # Current PNL emoji
            if pnl_pct > 0:
                emoji = "🟢"
            elif pnl_pct < 0:
                emoji = "🔴"
            else:
                emoji = "⚪"
            
            # Time open
            if time_open < 60:
                time_str = f"{time_open:.0f}s"
            elif time_open < 3600:
                time_str = f"{time_open/60:.1f}m"
            else:
                time_str = f"{time_open/3600:.1f}h"
            
            # TP targets
            tp_str = ""
            if tp_prices:
                tp_str = f" | TP: {', '.join([f'{tp:.6g}' for tp in tp_prices[:3]])}"
            
            lines.append(
                f"{idx}. {symbol} {side} {emoji}\n"
                f"   💰 {entry:.6g} → {current:.6g}\n"
                f"   📈 PNL: {pnl_pct:+.2f}% | {leverage}x\n"
                f"   ⏱️ {time_str} open | 🛑 SL: {sl_price:.6g if sl_price else 'N/A'}{tp_str}"
            )
    
    # Summary stats
    total_trades = len(trades)
    if total_trades > 0:
        win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
        lines.append(
            f"\n📊 <b>Summary Stats</b>\n"
            f"💰 Total PNL: +{total_pnl:.2f}$ ({total_pnl_pct:+.2f}%)\n"
            f"🎯 Win Rate: {win_rate:.1f}% ({winners}W/{losers}L)\n"
            f"🚀 Avg PNL/Trade: {total_pnl/total_trades:.2f}$"
        )
    
    return "\n".join(lines)

# ===================== EXPECTED PROFIT & TIME =====================
def format_expected_metrics(
    open_positions: List[Dict[str, Any]],
    historical_win_rate: float = 0.5,
    avg_tp_hit_time_minutes: float = 15
) -> str:
    """
    Format expected profit and time metrics
    """
    if not open_positions:
        return ""
    
    lines = ["💡 <b>Expected Metrics</b>"]
    
    total_risk = 0.0
    total_potential_profit = 0.0
    total_time_est = 0.0
    
    for pos in open_positions:
        symbol = pos.get("symbol", "?")
        entry = pos.get("entry_price", 0)
        sl_price = pos.get("sl_price", 0)
        tp_prices = pos.get("tp_prices", [])
        qty = pos.get("quantity", 0)
        
        # Calculate risk (entry to SL)
        risk_per_unit = abs(entry - sl_price) if sl_price else 0
        risk = risk_per_unit * qty
        total_risk += risk
        
        # Calculate potential profit (average of TPs)
        if tp_prices and entry > 0:
            avg_tp = sum(tp_prices) / len(tp_prices)
            profit_per_unit = abs(avg_tp - entry)
            potential_profit = profit_per_unit * qty
            total_potential_profit += potential_profit
        
        # Expected time to TP
        expected_time = avg_tp_hit_time_minutes
        total_time_est += expected_time
        
        tp_count = len(tp_prices)
        rr = (abs(avg_tp - entry) / risk_per_unit) if risk_per_unit > 0 else 0
        
        lines.append(
            f"{symbol}: Risk ${risk:.2f} | Reward ${potential_profit:.2f} | "
            f"RR: {rr:.2f} | ETA: {expected_time:.0f}m"
        )
    
    # Success probability
    success_prob = historical_win_rate * 100
    expected_profit = total_potential_profit * (success_prob / 100)
    expected_loss = total_risk * ((1 - success_prob / 100))
    net_expected = expected_profit - expected_loss
    
    lines.append(
        f"\n📈 <b>Expected Profit (based on {success_prob:.1f}% win rate)</b>\n"
        f"💚 Best case: +${expected_profit:.2f}\n"
        f"💔 Risk: -${expected_loss:.2f}\n"
        f"🎯 Net Expected: ${net_expected:+.2f}\n"
        f"⏱️ Avg Time to TP: ~{total_time_est/len(open_positions):.0f} minutes"
    )
    
    return "\n".join(lines)

# ===================== TP SUCCESS RATES =====================
def format_tp_success_rates(trades: List[Dict[str, Any]]) -> str:
    """
    Format TP hit success rates by percentage
    """
    if not trades:
        return ""
    
    lines = ["🎯 <b>TP Hit Success Rates</b>"]
    
    tp_hits = {}
    for trade in trades:
        tp_hit = trade.get("tp_hit", False)
        exit_reason = trade.get("exit_reason", "unknown")
        
        for tp_level in range(1, 6):
            tp_key = f"TP{tp_level}"
            if tp_key not in tp_hits:
                tp_hits[tp_key] = {"total": 0, "hits": 0}
            
            tp_hits[tp_key]["total"] += 1
            if tp_hit and f"TP{tp_level}" in exit_reason:
                tp_hits[tp_key]["hits"] += 1
    
    for tp_level in range(1, 6):
        tp_key = f"TP{tp_level}"
        if tp_key in tp_hits and tp_hits[tp_key]["total"] > 0:
            hit_rate = (tp_hits[tp_key]["hits"] / tp_hits[tp_key]["total"]) * 100
            bar_length = int(hit_rate / 10)
            bar = "█" * bar_length + "░" * (10 - bar_length)
            lines.append(f"{tp_key}: {bar} {hit_rate:.1f}%")
    
    return "\n".join(lines)

# ===================== ISSUES & FIXES =====================
def format_issues_and_fixes(
    issues: List[Dict[str, str]],
    system_score: float
) -> str:
    """
    Format detected issues and recommended fixes
    """
    if not issues and system_score > 50:
        return "✅ <b>No Issues Detected</b>\n✨ System operating normally!"
    
    lines = ["⚠️ <b>Issues & Recommended Fixes</b>"]
    
    for idx, issue in enumerate(issues, 1):
        problem = issue.get("problem", "Unknown")
        fix = issue.get("fix", "N/A")
        severity = issue.get("severity", "info")  # critical, warning, info
        
        severity_emoji = {
            "critical": "🔴",
            "warning": "🟠",
            "info": "🔵"
        }.get(severity, "🔵")
        
        lines.append(f"{severity_emoji} {idx}. {problem}\n   💡 Fix: {fix}")
    
    return "\n".join(lines)

# ===================== MAIN FORMATTER =====================
def format_rich_telegram_message(
    system_score: Dict[str, Any],
    active_brains: List[str],
    brain_scores: Dict[str, float],
    error_msgs: Dict[str, str],
    closed_trades: List[Dict[str, Any]] = None,
    open_positions: List[Dict[str, Any]] = None,
    issues: List[Dict[str, str]] = None,
    win_rate: float = 0.0,
    avg_tp_time: float = 15
) -> str:
    """
    Create comprehensive rich Telegram message with all metrics
    """
    sections = []
    
    # Header
    score_emoji = system_score.get("emoji", "🟡")
    score_val = system_score.get("total", 0)
    sections.append(
        f"בס\"ד\n\n"
        f"🤖 <b>AlgoGPT MetaBrain Status Report</b>\n"
        f"{score_emoji} System Score: <b>{score_val:.0f}/100</b>\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    # AI Brains Status
    sections.append(format_ai_brains_status(active_brains, brain_scores, error_msgs))
    sections.append("━━━━━━━━━━━━━━━━━━━━")
    
    # Trade Summary
    sections.append(format_trade_summary(closed_trades or [], open_positions or []))
    sections.append("━━━━━━━━━━━━━━━━━━━━")
    
    # Expected Metrics
    if open_positions:
        sections.append(format_expected_metrics(open_positions, win_rate, avg_tp_time))
        sections.append("━━━━━━━━━━━━━━━━━━━━")
    
    # TP Success Rates
    if closed_trades:
        sections.append(format_tp_success_rates(closed_trades))
        sections.append("━━━━━━━━━━━━━━━━━━━━")
    
    # Issues & Fixes
    sections.append(format_issues_and_fixes(issues or [], score_val))
    
    # Footer
    sections.append("━━━━━━━━━━━━━━━━━━━━")
    sections.append("בעזרת השם נעשה ונצליח 🙏")
    
    return "\n".join(filter(None, sections))


# ===================== SIMPLIFIED COMPACT FORMAT =====================
def format_compact_message(
    system_score: Dict[str, Any],
    active_brains: List[str],
    recent_trade: Optional[Dict[str, Any]] = None,
    open_count: int = 0
) -> str:
    """
    Compact message for quick updates (every trade or hourly)
    """
    score_emoji = system_score.get("emoji", "🟡")
    score_val = system_score.get("total", 0)
    active_count = len(active_brains)
    
    lines = [
        f"{score_emoji} Score: {score_val:.0f}/100 | AI: {active_count}/7 active",
    ]
    
    if recent_trade:
        symbol = recent_trade.get("symbol", "?")
        side = recent_trade.get("side", "?")
        pnl_pct = recent_trade.get("pnl_pct", 0)
        emoji = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < 0 else "⚪"
        lines.append(f"{emoji} {symbol} {side}: {pnl_pct:+.2f}%")
    
    if open_count > 0:
        lines.append(f"📍 {open_count} open position(s)")
    
    return " | ".join(lines)


if __name__ == "__main__":
    # Example usage
    sample_score = calculate_system_score(
        active_positions=1,
        total_pnl=50.0,
        win_rate=65.0,
        api_errors=0,
        trades_executed=5,
        leverage_avg=5.0,
        protection_active=True
    )
    
    sample_message = format_rich_telegram_message(
        system_score=sample_score,
        active_brains=["deepseek", "grok"],
        brain_scores={"deepseek": 7.5, "grok": 8.0},
        error_msgs={},
        closed_trades=[
            {
                "symbol": "ETHUSDT",
                "side": "LONG",
                "entry_price": 2750.0,
                "exit_price": 2800.0,
                "pnl_usd": 50.0,
                "pnl_pct": 1.82,
                "duration_sec": 900,
                "leverage": 5,
                "entry_time": time.time() - 900,
                "exit_time": time.time(),
                "exit_reason": "TP1_HIT",
                "tp_hit": True
            }
        ],
        open_positions=[],
        issues=[
            {
                "problem": "DeepSeek API quota low",
                "fix": "Replenish credits",
                "severity": "warning"
            }
        ],
        win_rate=0.65,
        avg_tp_time=15
    )
    
    print(sample_message)
