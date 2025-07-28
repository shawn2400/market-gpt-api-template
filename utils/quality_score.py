# utils/quality_score.py

def compute_quality_score(df):
    try:
        last = df.iloc[-1]
        score = 0

        # 1. ATR תקין
        if last.get("atr", 0) > 0:
            score += 1

        # 2. MACD חיובי מול הסיגנל
        if last.get("macd", 0) > last.get("macd_signal", 0):
            score += 1

        # 3. RSI בטווח נייטרלי (בין 35 ל־65)
        if 35 < last.get("rsi", 0) < 65:
            score += 1

        # 4. ADX חזק
        if last.get("adx", 0) > 17:
            score += 1

        # 5. Volume Spike
        if last.get("volume", 0) > last.get("volume_mean", 1) * 1.2:
            score += 1

        # 6. מחיר מעל EMA21
        if last.get("close", 0) > last.get("ema_21", 0):
            score += 1

        # 7. מחיר מעל EMA50
        if last.get("close", 0) > last.get("ema_50", 0):
            score += 1

        return round(score, 2)

    except Exception as e:
        print(f"[!] שגיאה בחישוב quality score: {e}")
        return 0



