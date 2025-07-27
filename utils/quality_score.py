def compute_quality_score(df):
    try:
        last = df.iloc[-1]
        score = 0

        if last.get("ATR", 0) > 0:
            score += 1
        if last.get("MACD", 0) > last.get("MACD_signal", 0):
            score += 1
        if 35 < last.get("RSI", 0) < 65:
            score += 1
        if last.get("ADX", 0) > 17:
            score += 1
        if last.get("volume", 0) > last.get("volume_mean", 1) * 1.2:
            score += 1
        if last.get("close", 0) > last.get("EMA21", 0):
            score += 1
        if last.get("close", 0) > last.get("EMA50", 0):
            score += 1

        return round(score, 2)
    except Exception as e:
        print(f"[!] שגיאה בחישוב quality score: {e}")
        return 0


