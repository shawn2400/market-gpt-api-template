# utils/quality_score.py

def compute_quality_score(data):
    """
    מחשב ציון איכות לטרייד לפי אינדיקטורים.
    מצפה למילון עם מפתחות: rsi, macd, adx, atr, volume_spike, pattern_score
    """
    try:
        score = 0
        if data.get("rsi") in range(50, 70):
            score += 2
        if data.get("macd", 0) > 0:
            score += 2
        if data.get("adx", 0) > 20:
            score += 2
        if data.get("volume_spike"):
            score += 2
        if data.get("pattern_score", 0) >= 1:
            score += 2
        return score  # ציון מתוך 10
    except Exception as e:
        print(f"[!] שגיאה בחישוב Quality Score: {e}")
        return 0

