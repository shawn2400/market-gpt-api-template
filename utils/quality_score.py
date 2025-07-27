def compute_quality_score(df_row):
    try:
        score = 0

        # תנודתיות (ATR)
        if df_row.get("atr", 0) > 0:
            score += 1

        # MACD חיובי
        if df_row.get("macd", 0) > 0:
            score += 1

        # RSI בין 35 ל־65 נחשב יציב
        if 35 < df_row.get("rsi", 0) < 65:
            score += 1

        # ADX מעל 17 – שוק עם מומנטום
        if df_row.get("adx", 0) > 17:
            score += 1

        # Volume Spike
        if df_row.get("volume", 0) > df_row.get("volume_mean", 1) * 1.2:
            score += 1

        # מחיר מעל EMA21 ב־LONG
        if df_row.get("direction", "LONG") == "LONG" and df_row.get("close", 0) > df_row.get("ema_21", 0):
            score += 1

        # מחיר מתחת ל־EMA ב־SHORT
        if df_row.get("direction", "LONG") == "SHORT" and df_row.get("close", 0) < df_row.get("ema_21", 0):
            score += 1

        return round(score, 2)
    except Exception as e:
        print(f"[!] שגיאה בחישוב quality score: {e}")
        return 0
