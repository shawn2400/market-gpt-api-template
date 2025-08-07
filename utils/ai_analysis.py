async def predict_optimal_sl_tp(entry_price: float, direction: str, symbol: str) -> dict:
    """
    חיזוי SL/TP אופטימליים לפי GPT בהתבסס על כיוון ומחיר כניסה.
    """
    if not openai.api_key:
        logging.error("[AI] ❌ מפתח OpenAI לא מוגדר.")
        return {"error": "OpenAI API key not configured"}

    try:
        prompt = (
            f"You are a professional crypto trading assistant.\n"
            f"The user wants to enter a {direction.upper()} trade on {symbol.upper()}.\n"
            f"Entry price is {entry_price:.4f} USDT.\n"
            f"Suggest an optimal Stop Loss and Take Profit price.\n"
            f"Return JSON with keys: 'sl', 'tp'. Do not include explanations.\n"
        )

        resp = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=100
        )

        raw_content = resp.choices[0].message.content.strip()
        logging.info(f"[AI] 🎯 פלט GPT לחיזוי SL/TP: {raw_content}")

        try:
            sl_tp = json.loads(raw_content)
            return {
                "sl": float(sl_tp.get("sl", 0)),
                "tp": float(sl_tp.get("tp", 0)),
                "raw": raw_content
            }
        except Exception as e:
            logging.warning(f"[AI] ❌ JSON parsing נכשל: {e}")
            return {"error": "Invalid format", "raw": raw_content}

    except Exception as e:
        logging.error(f"[AI] ❌ שגיאה בחיזוי SL/TP: {e}")
        return {"error": str(e)}














