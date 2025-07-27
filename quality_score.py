# utils/quality_score.py

def compute_quality_score(row):
    try:
        score = 0

        # תנודתיות ובריאות כללית
        if row["atr"] > 0:
            score += 1

        # MACD חיובי
        if row["macd"] > 0:
            score += 1

        # RSI בין 35 ל־65 נחשב יציב
        if 35 < row["rsi"] < 65:
            score += 1

        # ADX מעל 17 – שוק עם מומנטום
        if row["adx"] > 17:
            score += 1

        # Volume Spike
        if row["volume"] > row["volume_mean"] * 1.2:
            score += 1

        # המחיר מעל EMA21 ב־LONG
        if row.get("direction", "LONG") == "LONG" and row["close"] > row["ema_21"]:
            score += 1

        # או מתחת ל־EMA ב־SHORT
        if row.get("direction", "LONG") == "SHORT" and row["close"] < row["ema_21"]:
            score += 1

        # בונוס: סטיות תקן בולינגר בעתיד (דורש הרחבה עתידית)

        return round(score, 2)
    except Exception as e:
        print(f"[!] שגיאה בחישוב quality score: {e}")
        return 0

