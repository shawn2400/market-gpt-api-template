# utils/trade_reports.py
"""
מודול לדיווחי טרייד מפורטים - סיכום אחרי סגירה, דוחות יומיים, וכו'
"""
from __future__ import annotations
import os
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("algogpt.trade_reports")

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

def get_israel_time_str() -> str:
    """
    מחזיר timestamp נוכחי בשעון ישראל בפורמט יפה
    """
    now = datetime.now(ISRAEL_TZ)
    return now.strftime("%d/%m/%Y %H:%M:%S")

def get_israel_time() -> datetime:
    """
    מחזיר datetime נוכחי בשעון ישראל
    """
    return datetime.now(ISRAEL_TZ)

def is_trade_expired(created_at: str, max_age_hours: int = 2) -> bool:
    """
    בודק אם trade פג תוקף (יותר מידי זמן עבר מאז היצירה)
    """
    try:
        if not created_at:
            return False
        
        # Parse the timestamp
        if "T" in created_at:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            created = datetime.fromisoformat(created_at)
        
        now = datetime.now(timezone.utc)
        age_hours = (now - created).total_seconds() / 3600
        
        return age_hours > max_age_hours
    
    except Exception:
        return False

def grade_trade_section(value: float, thresholds: Dict[str, float]) -> tuple[str, str]:
    """
    נותן ציון לקטגוריה בטרייד
    Returns: (grade letter, emoji)
    """
    if value >= thresholds.get("A", 90):
        return "A+", "🏆"
    elif value >= thresholds.get("B", 80):
        return "A", "⭐"
    elif value >= thresholds.get("C", 70):
        return "B", "✅"
    elif value >= thresholds.get("D", 60):
        return "C", "⚠️"
    else:
        return "D", "❌"

def generate_trade_summary_report(trade_data: Dict[str, Any]) -> str:
    """
    יוצר דוח סיכום מפורט לטרייד שנסגר
    כולל ציונים, ניתוח, והמלצות לשיפור
    """
    symbol = trade_data.get("symbol", "UNKNOWN")
    side = trade_data.get("side", "LONG")
    
    # Extract trade metrics
    entry_price = float(trade_data.get("entry_price", 0))
    exit_price = float(trade_data.get("exit_price", 0))
    sl_price = float(trade_data.get("sl", 0))
    tp1 = float(trade_data.get("tp1", 0))
    
    pnl_usd = float(trade_data.get("pnl_usd", 0))
    pnl_pct = float(trade_data.get("pnl_pct", 0))
    
    duration_min = int(trade_data.get("duration_minutes", 0))
    max_dd_pct = abs(float(trade_data.get("max_drawdown_pct", 0)))
    
    # Calculate actual vs planned
    actual_rr = abs(pnl_pct / max_dd_pct) if max_dd_pct > 0 else 0
    planned_rr = trade_data.get("planned_rr", 0)
    
    # Grade each section
    sections = {}
    
    # 1. Entry Quality (timing, price vs plan)
    entry_quality = 75  # Base
    if entry_price > 0 and abs(exit_price - entry_price) / entry_price > 0.001:
        entry_quality += 10
    entry_grade, entry_emoji = grade_trade_section(entry_quality, {"A": 85, "B": 75, "C": 65, "D": 55})
    sections["entry"] = {
        "score": entry_quality,
        "grade": entry_grade,
        "emoji": entry_emoji,
        "comment": "כניסה טובה" if entry_quality >= 75 else "כניסה סבירה"
    }
    
    # 2. Risk Management
    risk_score = 80  # Base
    if max_dd_pct > 3:
        risk_score -= 20
    elif max_dd_pct < 1:
        risk_score += 10
    risk_grade, risk_emoji = grade_trade_section(risk_score, {"A": 85, "B": 75, "C": 65, "D": 55})
    sections["risk"] = {
        "score": risk_score,
        "grade": risk_grade,
        "emoji": risk_emoji,
        "comment": f"DD מקסימלי: {max_dd_pct:.2f}%"
    }
    
    # 3. Exit Quality
    exit_score = 70
    if pnl_pct > 0:
        exit_score += 20
    if abs(exit_price - tp1) / tp1 < 0.01:  # Close to TP1
        exit_score += 10
    exit_grade, exit_emoji = grade_trade_section(exit_score, {"A": 85, "B": 75, "C": 65, "D": 55})
    sections["exit"] = {
        "score": exit_score,
        "grade": exit_grade,
        "emoji": exit_emoji,
        "comment": "יציאה במטרה" if pnl_pct > 0 else "יציאה ב-SL"
    }
    
    # 4. Overall Performance
    overall_score = (entry_quality + risk_score + exit_score) / 3
    overall_grade, overall_emoji = grade_trade_section(overall_score, {"A": 85, "B": 75, "C": 65, "D": 55})
    
    # Build the report
    israel_time = get_israel_time_str()
    
    report = f"""
📊 <b>דוח סיכום טרייד - {symbol}</b>
🕐 <b>שעון ישראל:</b> {israel_time}

━━━━━━━━━━━━━━━━━━━━━━━━
💰 <b>תוצאות כספיות</b>
{'💚 רווח' if pnl_usd >= 0 else '❌ הפסד'}: <b>${pnl_usd:.2f}</b> ({pnl_pct:+.2f}%)
⏱ משך זמן: {duration_min} דקות

━━━━━━━━━━━━━━━━━━━━━━━━
📈 <b>ניתוח לפי מחלקות</b>

{sections['entry']['emoji']} <b>כניסה</b> - ציון: <b>{sections['entry']['grade']}</b>
   • {sections['entry']['comment']}
   • מחיר כניסה: ${entry_price:.4f}

{sections['risk']['emoji']} <b>ניהול סיכון</b> - ציון: <b>{sections['risk']['grade']}</b>
   • {sections['risk']['comment']}
   • RR בפועל: {actual_rr:.2f} (תוכנן: {planned_rr:.2f})

{sections['exit']['emoji']} <b>יציאה</b> - ציון: <b>{sections['exit']['grade']}</b>
   • {sections['exit']['comment']}
   • מחיר יציאה: ${exit_price:.4f}

━━━━━━━━━━━━━━━━━━━━━━━━
{overall_emoji} <b>ציון כולל: {overall_grade}</b> ({overall_score:.1f}/100)

━━━━━━━━━━━━━━━━━━━━━━━━
💡 <b>המלצות לשיפור:</b>
"""
    
    # Add specific recommendations
    recommendations = []
    
    if max_dd_pct > 2:
        recommendations.append("🔸 SL רחוק מדי - כדאי לצמצם את המרחק ל-SL")
    
    if actual_rr < planned_rr * 0.8:
        recommendations.append("🔸 RR בפועל נמוך מהתוכנית - שקול להדק TP או להרחיב SL")
    
    if duration_min < 30:
        recommendations.append("🔸 Trade קצר מדי - שקול timeframe גדול יותר")
    
    if pnl_pct < 0 and abs(pnl_pct) > 2:
        recommendations.append("🔸 הפסד גדול - בדוק שוב את איכות הסטאפ")
    
    if not recommendations:
        recommendations.append("✅ ביצוע מצוין! המשך כך")
    
    for rec in recommendations:
        report += f"\n{rec}"
    
    report += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━"
    
    return report

def generate_daily_digest(trades: List[Dict[str, Any]], date_str: Optional[str] = None) -> str:
    """
    יוצר דוח סיכום יומי
    """
    israel_time = get_israel_time_str()
    if not date_str:
        date_str = datetime.now(ISRAEL_TZ).strftime("%d/%m/%Y")
    
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if float(t.get("pnl_usd", 0)) > 0)
    losing_trades = total_trades - winning_trades
    
    total_pnl = sum(float(t.get("pnl_usd", 0)) for t in trades)
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    # Group by symbol
    symbols_traded = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        symbols_traded[sym] = symbols_traded.get(sym, 0) + 1
    
    most_traded = max(symbols_traded.items(), key=lambda x: x[1]) if symbols_traded else ("N/A", 0)
    
    report = f"""
🌅 <b>דוח סיכום יומי - {date_str}</b>
🕐 <b>שעון ישראל:</b> {israel_time}

━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>סטטיסטיקות כלליות</b>

📈 סה"כ טרייד: <b>{total_trades}</b>
💚 ניצחונות: <b>{winning_trades}</b> ({win_rate:.1f}%)
❌ הפסדים: <b>{losing_trades}</b>

━━━━━━━━━━━━━━━━━━━━━━━━
💰 <b>תוצאות כספיות</b>

סה"כ PNL: <b>${total_pnl:+.2f}</b>
ממוצע לטרייד: <b>${avg_pnl:+.2f}</b>

━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>מטבעות נסחרים</b>

הכי נסחר: <b>{most_traded[0]}</b> ({most_traded[1]} טרייד)
סה"כ מטבעות שונים: <b>{len(symbols_traded)}</b>

━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    # Add top performers
    if trades:
        sorted_trades = sorted(trades, key=lambda t: float(t.get("pnl_usd", 0)), reverse=True)
        best_trade = sorted_trades[0]
        worst_trade = sorted_trades[-1]
        
        report += f"""
🏆 <b>הטרייד הטוב ביותר:</b>
   {best_trade.get('symbol', 'N/A')} - <b>${float(best_trade.get('pnl_usd', 0)):+.2f}</b>

⚠️ <b>הטרייד החלש ביותר:</b>
   {worst_trade.get('symbol', 'N/A')} - <b>${float(worst_trade.get('pnl_usd', 0)):+.2f}</b>

━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    # Overall assessment
    if win_rate >= 70:
        assessment = "🎉 יום מצוין! המשך ככה!"
    elif win_rate >= 50:
        assessment = "✅ יום טוב, אבל יש מקום לשיפור"
    else:
        assessment = "⚠️ יום מאתגר - בדוק את האסטרטגיה"
    
    report += f"\n{assessment}\n━━━━━━━━━━━━━━━━━━━━━━━━"
    
    return report

def send_trade_summary_telegram(trade_data: Dict[str, Any]):
    """
    שולח דוח סיכום טרייד ל-Telegram
    """
    try:
        from utils.alerts import send_telegram_message
        
        report = generate_trade_summary_report(trade_data)
        send_telegram_message(report, parse_mode="HTML")
        logger.info("Trade summary report sent to Telegram")
    
    except Exception as e:
        logger.error(f"Failed to send trade summary: {e}")

def send_daily_digest_telegram(trades: List[Dict[str, Any]]):
    """
    שולח דוח יומי ל-Telegram
    """
    try:
        from utils.alerts import send_telegram_message
        
        report = generate_daily_digest(trades)
        send_telegram_message(report, parse_mode="HTML")
        logger.info("Daily digest sent to Telegram")
    
    except Exception as e:
        logger.error(f"Failed to send daily digest: {e}")
