# utils/decision_engine.py
from __future__ import annotations
import logging
from typing import Dict, Any
from utils.ai_analysis import analyze_with_ai

logger = logging.getLogger("algogpt.decision")

async def make_decision(features: Dict[str, Any], quality_score: float) -> Dict[str, Any]:
    """
    מחליט אם לבצע טרייד או לא.
    - quality_score הוא הציון המספרי.
    - אם יש GPT → מוסיף ניתוח טקסטואלי.
    - אם אין GPT → מייצר Fallback בסיסי.
    """
    symbol = features.get("symbol", "UNKNOWN")
    side = features.get("side", "LONG")
    entry = features.get("entry")
    sl = features.get("sl")
    tp1 = features.get("tp1")

    # GPT analysis
    ai_summary = ""
    try:
        ai_res = await analyze_with_ai(features)
        if ai_res.get("ok"):
            ai_summary = ai_res["analysis"]
        else:
            ai_summary = f"[Fallback] {symbol} {side} score={quality_score:.2f} entry={entry}, SL={sl}, TP1={tp1}"
    except Exception as e:
        ai_summary = f"[AI error → fallback] {symbol} {side} {quality_score:.2f} | entry={entry}, SL={sl}, TP1={tp1}"
        logger.error(f"AI analysis failed: {e}")

    decision = {
        "symbol": symbol,
        "side": side,
        "quality_score": quality_score,
        "ai_summary": ai_summary,
        "approved": quality_score >= 8.5,  # תנאי סף
    }
    return decision









