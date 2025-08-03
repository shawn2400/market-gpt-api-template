from utils.ws_fallback import get_price, is_price_fresh
...

async def executor_loop(...):
    ...
    for trade in results:
        if trade["quality_score"] >= min_quality:
            # ---- הגנה: אם אין מחיר עדכני – דלג/התרע!
            symbol = trade["symbol"]
            if not is_price_fresh(symbol):
                print(f"[AutoExecutor] ⚠️ מחיר ל־{symbol} לא עדכני – דילוג על הטרייד.")
                continue

            price = get_price(symbol)
            if not price or price <= 0:
                print(f"[AutoExecutor] ⚠️ מחיר לא תקין עבור {symbol}")
                continue

            ...









































