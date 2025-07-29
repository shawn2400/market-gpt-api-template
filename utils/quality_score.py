# utils/quality_score.py

import logging
import numpy as np

def compute_quality_score(df, verbose=False) -> float:
    """
    מחשב ציון איכות לטרייד (0–10) לפי אינדיקטורים טכניים.
    """
    try:
        last = df.iloc[-1]
        score = 0
        max_score = 10
        reasons = []

        # 1. ATR קיים
        atr = last.get("atr", 0)
        if atr and atr > 0:
            score += 1
            reasons.append("ATR תקין")

        # 2. MACD מעל הסיגנל
        macd = last.get("macd", 0)
        macd_signal = last.get("macd_signal", 0)
        if macd > macd_signal:
            score += 1
            reasons.append("MACD חיובי")

        # 3. RSI נייטרלי (45–65)
        rsi = last.get("rsi", 0)
        if 45 <= rsi <= 65:
            score += 1
            reasons.append("RSI נייטרלי")

        # 4. ADX מעל 20
        adx = last.get("adx", 0)
        if adx > 20:
            score += 1
            reasons.append("ADX חזק")

        # 5. נפח גבוה
        vol = last.get("volume", 0)
        vol_mean = last.get("volume_mean", 1)
        if vol > vol_mean * 1.5:
            score += 1
            reasons.append("נפח גבוה")

        # 6. מחיר מעל EMA21
        close = last.get("close", 0)
        ema21 = last.get("ema_21", 0)
        if close > ema21:
            score += 1
            reasons.append("מעל EMA21")

        # 7. מחיר מעל EMA50
        ema50 = last.get("ema_50", 0)
        if close > ema50:
            score += 1
            reasons.append("מעל EMA50")

        # 8. EMA21 חוצה מעל EMA50
        prev = df.iloc[-2] if len(df) > 1 else last
        if last.get("ema_21", 0) > last.get("ema_50", 0) and prev.get("ema_21", 0) <= prev.get("ema_50", 0):
            score += 1
            reasons.append("חציית EMA21 מעל EMA50")

        # 9. MACD Histogram חיובי
        if last.get("macd_hist", 0) > 0:
            score += 1
            reasons.append("MACD היסטוגרמה חיובי")

        # 10. VWAP – המחיר מעל
        vwap = last.get("vwap", 0)
        if close > vwap:
            score += 1
            reasons.append("מעל VWAP")

        final_score = min(round(score, 2), max_score)

        if verbose:
            logging.info(f"[quality_score] score={final_score} | סיבות: {', '.join(reasons)}")

        return final_score

    except Exception as e:
        logging.error(f"[quality_score] שגיאה: {e}")
        return 0.0





