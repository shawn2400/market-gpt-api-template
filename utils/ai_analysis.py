# utils/ai_analysis.py
from __future__ import annotations
import logging
from typing import Tuple, Optional

from utils.ai_client import chat

logger = logging.getLogger(__name__)

# נשתמש בספי קונפיג עבור פולבק SL/TP בטוח
try:
    from utils import config as cfg  # type: ignore
except Exception:
    class _C:
        SL_MIN_PCT = 0.20
        SL_MAX_PCT = 5.00
        TP_MIN_PCT = 0.30
        TP_MAX_PCT = 8.00
    cfg = _C()  # type: ignore

def _clip_pct(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

async def analyze_with_ai(data: dict) -> str:
    """
    החזרת ניתוח קצר (עברית), עם retries פנימיים ב-ai_client.
    """
    prompt = (
        f"ספק ניתוח קצר למטבע {data.get('symbol','?')}:\n"
        f"• RSI: {data.get('rsi')}\n"
        f"• ADX: {data.get('adx')}\n"
        f"• מגמה: {data.get('trend')}\n"
        f"• תבנית: {data.get('pattern')}\n"
        f"• נפח: {data.get('volume')}\n"
        f"סיים בשורה אחת: המלצה (LONG/SHORT/HOLD) ונימוק בן 3–6 מילים."
    )
    txt = await chat(prompt, system="אתה אנליסט שוק קריפטו מקצועי. כתוב תמציתי.", temperature=0.3, max_tokens=220)
    return txt.strip() if txt else "❌ ניתוח GPT נכשל"

def _parse_sltp(text: str) -> Optional[Tuple[float, float]]:
    t = (text or "").replace(" ", "").upper()
    if "SL=" in t and "TP=" in t:
        try:
            sl_s = t.split("SL=")[1].split(",")[0]
            tp_s = t.split("TP=")[1].split("\n")[0]
            return float(sl_s), float(tp_s)
        except Exception:
            return None
    return None

async def predict_optimal_sl_tp(symbol: str, direction: str, entry_price: float, atr: float | None = None) -> tuple[float, float]:
    """
    מנסה GPT; אם נכשל — פולבק דטרמיניסטי לפי אחוזים בטווחים המוגדרים.
    """
    sys = "אתה מחשב SL/TP עבור טריידים בזמן אמת. החזר אך ורק בפורמט: SL=..., TP=..."
    prompt = (
        f"ספק SL ו-TP לטרייד:\n"
        f"• סימבול: {symbol}\n"
        f"• כיוון: {direction}\n"
        f"• מחיר כניסה: {entry_price}\n"
        f"• ATR (לא חובה): {atr if atr else 'N/A'}\n\n"
        f"החזר רק: SL=..., TP=..."
    )
    txt = await chat(prompt, system=sys, temperature=0.2, max_tokens=32)
    parsed = _parse_sltp(txt)
    if parsed:
        sl, tp = parsed
        if sl > 0 and tp > 0:
            return float(sl), float(tp)

    # פולבק: נגזרות אחוזיות בטוחות
    long = str(direction).upper() == "LONG"
    # אם ATR סביר — אפשר לשלב (מינורי) בעתיד; עתה נישאר בפולבק לפי אחוזים לשקיפות.
    sl_pct = _clip_pct(0.60, cfg.SL_MIN_PCT, cfg.SL_MAX_PCT)  # 0.60% כברירת מחדל באמצע התחום
    tp_pct = _clip_pct(2.00, cfg.TP_MIN_PCT, cfg.TP_MAX_PCT)  # 2.00% ברירת מחדל

    if long:
        sl = entry_price * (1.0 - sl_pct / 100.0)
        tp = entry_price * (1.0 + tp_pct / 100.0)
    else:
        sl = entry_price * (1.0 + sl_pct / 100.0)
        tp = entry_price * (1.0 - tp_pct / 100.0)

    return round(sl, 6), round(tp, 6)

# התאמה לאחור לחתימות ישנות
async def predict_optimal_sl_tp_legacy(symbol: str, direction: str, entry: float) -> tuple:
    return await predict_optimal_sl_tp(symbol, direction, entry_price=entry, atr=None)







































