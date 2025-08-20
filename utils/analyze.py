# utils/analyze.py
"""
Analyzer module for AlgoGPT.
משמש את /ai/manual-scan להחזיר אינדיקטורים בסיסיים גם אם אין ניתוח מלא.
"""

from typing import Dict, Any

def analyze_symbol(symbol: str, market: str = "futures", interval: str = "15m") -> Dict[str, Any]:
    """
    מחזיר מבנה בסיסי של ניתוח טכני.
    בפועל אפשר להרחיב ולקרוא ל-utils.indicators אם קיים.
    """
    try:
        # ⚡ כאן בעתיד תוכל להחליף בחישובי אינדיקטורים אמיתיים
        return {
            "symbol": symbol,
            "market": market,
            "interval": interval,
            "trend": "neutral",
            "direction": "sideways",
            "rsi": 50.0,
            "adx": 20.0,
            "volume": 100000.0,
            "quality_score": 5,
            "signal": "hold",
            "confidence": 0.5,
            "reason": "mock-analyze",   # לצורך fallback
            "close": 50000.0,
            "atr": 100.0,
        }
    except Exception as e:
        return {"symbol": symbol, "market": market, "interval": interval, "error": str(e)}

