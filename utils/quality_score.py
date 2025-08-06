# utils/quality_score.py

import logging
import numpy as np
import pandas as pd

def compute_quality_score(df, verbose=False) -> float:
    """
    מחשב ציון איכות לטרייד (0–10) לפי אינדיקטורים טכניים.
    תומך ב־DataFrame (שורת אחרונה) או dict.
    """
    try:
        # --- שליפה ---
        if isinstance(df, pd.DataFrame) and not df.empty:
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None
        elif isinstance(df, dict):
            last = df
            prev = None
        else:
            logging.warning("[quality_score] סוג נתון לא נתמך")
            return 0.0

        score = 0
        reasons = []

        # --- ATR ---
        atr = last.get("atr")
        if isinstance(atr, (int, float)) and atr > 0:
            score += 1
            reasons.append("ATR תקין")

        # --- MACD ---
        macd = last.get("macd", 0)
        macd_signal = last.get("macd_signal", 0)
        if macd > macd_signal:
            score += 1
            reasons.append("MACD חיובי")

        # --- RSI ---
        rsi = last.get("rsi", 0)
        if 45 <= rsi <= 65:
            score += 1
            reasons.append("RSI נייטרלי")

        # --- ADX ---
        adx = last.get("adx", 0)
        if adx > 20:
            score += 1
            reasons.append("ADX חזק")

        # --- נפח ---
        vol = last.get("volume", 0)
        vol_mean = last.get("volume_mean", 1)
        if isinstance(vol, (int, float)) and isinstance(vol_mean, (int, float)) and vol > vol_mean * 1.5:
            score += 1
            reasons.append("נפח גבוה")

        # --- EMA21 / EMA50 ---
        close = last.get("close", 0)
        ema21 = last.get("ema_21", 0)
        ema50 = last.get("ema_50", 0)

        if close > ema21:
            score += 1
            reasons.append("מעל EMA21")

        if close > ema50:
            score += 1
            reasons.append("מעל EMA50")

        # --- חציית EMA21 מעל EMA50 ---
        if prev is not None:
            if ema21 > ema50 and prev.get("ema_21", 0) <= prev.get("ema_50", 0):
                score += 1
                reasons.append("חציית EMA21 מעל EMA50")

        # --- MACD Histogram ---
        macd_hist = last.get("macd_hist", 0)
        if macd_hist > 0:
            score += 1
            reasons.append("MACD היסטוגרמה חיובי")

        # --- VWAP ---
        vwap = last.get("vwap", 0)
        if close > vwap:
            score += 1
            reasons.append("מעל VWAP")

        final_score = min(round(score, 2), 10.0)

        if verbose:
            logging.info(f"[quality_score] ✅ ציון איכות: {final_score} | סיבות: {', '.join(reasons)}")

        return final_score

    except Exception as e:
        logging.error(f"[quality_score] ❌ שגיאה: {e}")
        return 0.0

# === עטיפת compute_quality_score עבור תאימות ===
def calculate_quality_score(indicators: dict) -> float:
    return compute_quality_score(indicators, verbose=False)











