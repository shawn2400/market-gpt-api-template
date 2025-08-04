# utils/quality_score.py
import logging
import numpy as np
import pandas as pd

def compute_quality_score(df, verbose=False) -> float:
    """
    מחשב ציון איכות לטרייד (0–10) לפי אינדיקטורים טכניים.
    """
    try:
        if isinstance(df, pd.DataFrame) and not df.empty:
            last = df.iloc[-1]
        else:
            last = df  # ייתכן שמועבר dict

        if not hasattr(last, "get"):
            raise TypeError("שורת הנתונים לא כוללת מתודת get – סוג שגוי")

        score = 0
        max_score = 10
        reasons = []

        # ATR
        atr = last.get("atr", 0)
        if atr and atr > 0:
            score += 1
            reasons.append("ATR תקין")

        # MACD מעל סיגנל
        macd = last.get("macd", 0)
        macd_signal = last.get("macd_signal", 0)
        if macd > macd_signal:
            score += 1
            reasons.append("MACD חיובי")

        # RSI נייטרלי (45–65)
        rsi = last.get("rsi", 0)
        if 45 <= rsi <= 65:
            score += 1
            reasons.append("RSI נייטרלי")

        # ADX
        adx = last.get("adx", 0)
        if adx > 20:
            score += 1
            reasons.append("ADX חזק")

        # נפח גבוה
        vol = last.get("volume", 0)
        vol_mean = last.get("volume_mean", 1)
        if isinstance(vol, (int, float)) and isinstance(vol_mean, (int, float)) and vol > vol_mean * 1.5:
            score += 1
            reasons.append("נפח גבוה")

        # מעל EMA21
        close = last.get("close", 0)
        ema21 = last.get("ema_21", 0)
        if isinstance(close, (int, float)) and isinstance(ema21, (int, float)) and close > ema21:
            score += 1
            reasons.append("מעל EMA21")

        # מעל EMA50
        ema50 = last.get("ema_50", 0)
        if isinstance(close, (int, float)) and isinstance(ema50, (int, float)) and close > ema50:
            score += 1
            reasons.append("מעל EMA50")

        # חציית EMA21 מעל EMA50
        if isinstance(df, pd.DataFrame) and len(df) > 1:
            prev = df.iloc[-2]
            if (
                last.get("ema_21", 0) > last.get("ema_50", 0) and
                prev.get("ema_21", 0) <= prev.get("ema_50", 0)
            ):
                score += 1
                reasons.append("חציית EMA21 מעל EMA50")

        # MACD Histogram חיובי
        if last.get("macd_hist", 0) > 0:
            score += 1
            reasons.append("MACD היסטוגרמה חיובי")

        # VWAP – המחיר מעל
        vwap = last.get("vwap", 0)
        if isinstance(close, (int, float)) and isinstance(vwap, (int, float)) and close > vwap:
            score += 1
            reasons.append("מעל VWAP")

        final_score = min(round(score, 2), max_score)

        if verbose:
            logging.info(f"[quality_score] score={final_score} | סיבות: {', '.join(reasons)}")

        return final_score

    except Exception as e:
        logging.error(f"[quality_score] שגיאה: {e}")
        return 0.0









