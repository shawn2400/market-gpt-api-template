def calculate_sl_tp(df, direction):
    if df.empty or "close" not in df.columns:
        raise ValueError("ה־DataFrame ריק או חסרה עמודת close")

    entry = float(df["close"].iloc[-1])
    sl_pct = 0.01
    tp_pct = 0.015

    if direction.upper() == "LONG":
        return {
            "stop": round(entry * (1 - sl_pct), 4),
            "tp": round(entry * (1 + tp_pct), 4)
        }
    elif direction.upper() == "SHORT":
        return {
            "stop": round(entry * (1 + sl_pct), 4),
            "tp": round(entry * (1 - tp_pct), 4)
        }
    else:
        raise ValueError("כיוון לא חוקי: חייב להיות 'LONG' או 'SHORT'")
