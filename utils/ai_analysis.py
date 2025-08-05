import os
import openai
import logging
import re
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

async def analyze_with_ai(
    symbol: str,
    rsi: float,
    adx: float,
    trend: str,
    pattern: str,
    volume: float
) -> dict:
    if not openai.api_key:
        logging.error("[AI] ❌ לא הוגדר מפתח OpenAI.")
        return {"error": "No OpenAI API key configured"}

    logging.info(f"[AI] 🔍 התחיל ניתוח GPT עבור {symbol}")

    prompt = (
        f"Analyze the following market data for {symbol}:\n"
        f"- RSI: {rsi}\n"
        f"- ADX: {adx}\n"
        f"- Trend: {trend}\n"
        f"- Pattern: {pattern}\n"
        f"- Volume: {volume}\n\n"
        "Please provide a trading recommendation (BUY/SELL/HOLD) and a confidence score."
    )

    try:
        resp = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert crypto trading assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=150
        )

        if not resp.choices:
            logging.warning(f"[AI] ⚠️ לא התקבלה תשובה מ־OpenAI עבור {symbol}")
            return {"signal": "HOLD", "confidence": 0.0}

        content = resp.choices[0].message.content
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        result = {"signal": "HOLD", "confidence": 0.0}

        for line in lines:
            up = line.upper()
            if up.startswith(("BUY", "SELL", "HOLD")):
                result["signal"] = up.split()[0]
            if "CONFIDENCE" in up:
                m = re.search(r"(\d+(\.\d+)?)", line)
                if m:
                    result["confidence"] = float(m.group(1))

        logging.info(f"[AI] 🧠 המלצה ל-{symbol}: {result}")
        return result

    except Exception as e:
        logging.error(f"[AI] ❌ שגיאה בקריאת OpenAI: {e}")
        return {"error": str(e), "signal": "HOLD", "confidence": 0.0}









