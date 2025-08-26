# utils/ai_analysis.py
from __future__ import annotations
import logging
from typing import Dict

logger = logging.getLogger(__name__)

try:
    from utils.ai_client import chat
except Exception as _e:
    chat = None  # type: ignore
    logger.warning("⚠️ utils.ai_analysis: ai_client.chat not available: %s", _e)

def _clip_pct(x: float, lo: float, hi: float) -> float:
    try:
        return max(float(lo), min(float(hi), float(x)))
    except Exception:
        return x

async def analyze_with_ai(data: Dict) -> Dict:
    """קריאה ל־GPT. מחזיר dict עם ok + analysis (string)."""
    symbol = data.get("symbol", "?")
    try:
        if chat is None:
            raise RuntimeError("AI client not available (chat=None)")

        prompt = (
            f"ספק ניתוח קצר למטבע {symbol}:\n"
            f"• RSI: {data.get('rsi')}\n"
            f"• ADX: {data.get('adx')}\n"
            f"• מגמה: {data.get('trend')}\n"
            f"• תבנית: {data.get('pattern')}\n"
            f"• נפח: {data.get('volume')}\n"
            f"סיים בשורה אחת: המלצה (LONG/SHORT/HOLD) ונימוק קצר."
        )

        txt = await chat(
            prompt,
            system="אתה אנליסט שוק קריפטו מקצועי.",
            temperature=0.3,
            max_tokens=220,
        )
        return {"ok": True, "analysis": (txt or "").strip()}
    except Exception as e:
        logger.warning("⚠️ analyze_with_ai fallback (%s): %s", symbol, e)
        return {"ok": False, "analysis": "❌ ניתוח GPT נכשל"}












































