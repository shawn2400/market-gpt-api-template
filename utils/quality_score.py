# utils/quality_score.py
import logging
import numpy as np
import pandas as pd

def compute_quality_score(df, verbose: bool = False) -> float:
    """
    מחשב ציון איכות לטרייד (0–10) לפי אינדיקטורים טכניים.
    תומך ב־DataFrame (שורה אחרונה) או dict.
    """
    try:
        if isinstance(df, pd.DataFrame) and not df.empty:
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None
        elif isinstance(df, dict):
            last = df
            prev = None
        else:
            logging.warning("[quality_score] סוג נתון לא נתמך")
            return 0.0

        def f(x, default=0.0):
            try:
                return float(x)
            except Exception:
                return float(default)

        score = 0
        reasons = []

        # ATR
        atr = f(last.get("atr"), 0)
        if atr > 0:
            score += 1; reasons.append("ATR תקין")

        # MACD
        macd = f(last.get("macd"), 0); macd_signal = f(last.get("macd_signal"), 0)
        if macd > macd_signal:
            score += 1; reasons.append("MACD חיובי")

        # RSI
        rsi = f(last.get("rsi"), 0)
        if 45 <= rsi <= 65:
            score += 1; reasons.append("RSI נייטרלי")

        # ADX
        adx = f(last.get("adx"), 0)
        if adx > 20:
            score += 1; reasons.append("ADX חזק")

        # Volume
        vol = f(last.get("volume"), 0); vol_mean = max(1e-9, f(last.get("volume_mean"), 1))
        if vol > vol_mean * 1.5:
            score += 1; reasons.append("נפח גבוה")

        # EMA checks
        close = f(last.get("close"), 0)
        ema21 = f(last.get("ema_21"), close)
        ema50 = f(last.get("ema_50"), close)

        if close > ema21:
            score += 1; reasons.append("מעל EMA21")
        if close > ema50:
            score += 1; reasons.append("מעל EMA50")

        if prev is not None:
            if ema21 > ema50 and f(prev.get("ema_21")) <= f(prev.get("ema_50")):
                score += 1; reasons.append("חציית EMA21 מעל EMA50")

        macd_hist = f(last.get("macd_hist"), 0)
        if macd_hist > 0:
            score += 1; reasons.append("MACD היסטוגרמה חיובי")

        vwap = f(last.get("vwap"), close)
        if close > vwap:
            score += 1; reasons.append("מעל VWAP")

        final_score = float(min(max(score, 0), 10))
        if verbose:
            logging.info(f"[quality_score] ✅ ציון איכות: {final_score} | סיבות: {', '.join(reasons)}")
        return final_score
    except Exception as e:
        logging.error(f"[quality_score] ❌ שגיאה: {e}", exc_info=True)
        return 0.0

def calculate_quality_score(indicators: dict) -> float:
    return compute_quality_score(indicators, verbose=False)












