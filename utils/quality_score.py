def compute_quality_score(df_row):
    try:
        score = 0

        if df_row.get("atr", 0) > 0:
            score += 1
        if df_row.get("macd", 0) > 0:
            score += 1
        if 35 < df_row.get("rsi", 0) < 65:
            score += 1
        if df_row.get("adx", 0) > 17:
            score += 1
        if df_row.get("volume", 0) > df_row.get("volume_mean", 1) * 1.2:
            score += 1

        if df_row.get("direction", "LONG") == "LONG" and df_row.get("close", 0) > df_row.get("ema_21", 0):
            score += 1
        if df_row.get("direction") == "SHORT" and df_row.get("close", 0) < df_row.get("ema_21", 0):
            score += 1

        return round(score, 2)
    except Exception as e:
        print(f"[!] שגיאה בחישוב quality score: {e}")
        return 0

