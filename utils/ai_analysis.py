# utils/ai_analysis.py
from __future__ import annotations
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# --- Import AI client ---
try:
    from utils.ai_client import chat
except Exception as _e:
    chat = None  # type: ignore
    logger.warning("utils.ai_analysis: ai_client.chat not available: %s", _e)

# --- Fallback config if utils.config not available ---
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


async def analyze_with_ai(data: dict) -> str:
    """
    מחזיר ניתוח קצר (עברית) עם GPT.
    אם GPT נכשל → fallback עם הודעת כשל.
    """
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
        if txt:
            return str(txt).strip()
        return "❌ ניתוח GPT נכשל"
    except Exception as e:
        logger.warning("⚠️ analyze_with_ai fallback (%s): %s", symbol, e)
        return "❌ ניתוח GPT נכשל"


def _parse_sltp(text: str) -> Optional[Tuple[float, float]]:
    """
    פרסר פשוט ל־SL=..., TP=...
    """
    t = (text or "").replace(" ", "").upper()
    if "SL=" in t and "TP=" in t:
        try:
            sl_s = t.split("SL=")[1].split(",")[0]
            tp_s = t.split("TP=")[1].split("\n")[0]
            sl_v = float(sl_s)
            tp_v = float(tp_s)
            if sl_v > 0 and tp_v > 0:
                return sl_v, tp_v
        except Exception as e:
            logger.warning("⚠️ parse SL/TP failed: %s", e)
    return None


async def predict_optimal_sl_tp(
    symbol: str,
    direction: str,
    entry_price: float,
    atr: float | None = None,
) -> tuple[float, float]:
    """
    חיזוי SL/TP עם GPT. אם נכשל → fallback דטרמיניסטי בטוח.
    """
    try:
        if chat is None:
            raise RuntimeError("AI client not available")

        sys = "אתה מחשב SL/TP לטרייד בזמן אמת. החזר בפורמט: SL=..., TP=..."
        prompt = (
            f"ספק SL ו-TP לטרייד:\n"
            f"• סימבול: {symbol}\n"
            f"• כיוון: {direction}\n"
            f"• מחיר כניסה: {entry_price}\n"
            f"• ATR: {atr if atr else 'N/A'}\n\n"
            f"החזר רק: SL=..., TP=..."
        )

        txt = await chat(prompt, system=sys, temperature=0.2, max_tokens=32)
        parsed = _parse_sltp(txt or "")
        if parsed:
            sl, tp = parsed
            if sl > 0 and tp > 0:
                return float(sl), float(tp)
    except Exception as e:
        logger.warning("⚠️ GPT SL/TP failed (%s): %s", symbol, e)

    # --- Safe fallback ---
    long = str(direction).upper() == "LONG"
    sl_pct = _clip_pct(0.60, cfg.SL_MIN_PCT, cfg.SL_MAX_PCT)  # 0.6%
    tp_pct = _clip_pct(2.00, cfg.TP_MIN_PCT, cfg.TP_MAX_PCT)  # 2%

    if entry_price <= 0:
        return 0.0, 0.0

    if long:
        sl = entry_price * (1 - sl_pct / 100.0)
        tp = entry_price * (1 + tp_pct / 100.0)
    else:
        sl = entry_price * (1 + sl_pct / 100.0)
        tp = entry_price * (1 - tp_pct / 100.0)

    return round(float(sl), 6), round(float(tp), 6)


# תאימות לאחור
async def predict_optimal_sl_tp_legacy(symbol: str, direction: str, entry: float) -> tuple[float, float]:
    return await predict_optimal_sl_tp(symbol, direction, entry_price=entry)










































