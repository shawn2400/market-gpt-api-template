# utils/ai_analysis.py
from __future__ import annotations
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

try:
    from utils.ai_client import chat
except Exception as _e:
    chat = None  # type: ignore
    logger.warning("utils.ai_analysis: ai_client.chat not available: %s", _e)

try:
    from utils import config as cfg
except Exception:
    class _C:
        SL_MIN_PCT = 0.20
        SL_MAX_PCT = 5.00
        TP_MIN_PCT = 0.30
        TP_MAX_PCT = 8.00
    cfg = _C()

def _clip_pct(x: float, lo: float, hi: float) -> float:
    try:
        return max(float(lo), min(float(hi), float(x)))
    except Exception:
        return x

async def analyze_with_ai(data: dict) -> dict:
    """מחזיר dict עם ok=True ותוצאה מ־GPT או fallback."""
    symbol = data.get("symbol", "?")
    try:
        if chat is None:
            raise RuntimeError("AI client not available")

        prompt = (
            f"ספק ניתוח קצר למטבע {symbol}:\n"
            f"• RSI: {data.get('rsi')}\n"
            f"• ADX: {data.get('adx')}\n"
            f"• מגמה: {data.get('trend')}\n"
            f"• תבנית: {data.get('pattern')}\n"
            f"• נפח: {data.get('volume')}\n"
            f"סיים בשורה אחת: המלצה (LONG/SHORT/HOLD) ונימוק קצר."
        )
        txt = await chat(prompt, system="אתה אנליסט שוק קריפטו מקצועי.", temperature=0.3, max_tokens=220)
        return {"ok": True, "analysis": (txt or "❌ ניתוח GPT נכשל").strip()}
    except Exception as e:
        logger.warning("⚠️ analyze_with_ai fallback (%s): %s", symbol, e)
        return {"ok": False, "analysis": "❌ ניתוח GPT נכשל"}











































