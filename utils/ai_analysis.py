import os
import openai
from utils.binance_client import client

openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_ai(
    symbol: str,
    rsi: float,
    adx: float,
    trend: str,
    pattern: str,
    volume: float
) -> dict:
    prompt = (
        f"Analyze the following market data for {symbol}:\n"
        f"- RSI: {rsi}\n"
        f"- ADX: {adx}\n"
        f"- Trend: {trend}\n"
        f"- Pattern: {pattern}\n"
        f"- Volume: {volume}\n\n"
        "Please provide a trading recommendation (BUY/SELL/HOLD) and a confidence score."
    )
    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert crypto trading assistant."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.0,
        max_tokens=150
    )
    content = resp.choices[0].message.content
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    result = {}
    for line in lines:
        up = line.upper()
        if up.startswith(("BUY", "SELL", "HOLD")):
            result["signal"] = up.split()[0]
        if "CONFIDENCE" in up:
            import re
            m = re.search(r"(\d+(\.\d+)?)", line)
            if m:
                result["confidence"] = float(m.group(1))
    return result

def predict_optimal_sl_tp(
    symbol: str,
    entry_price: float,
    rsi: float,
    adx: float,
    trend: str
) -> dict:
    """
    מייצר המלצה על Stop-Loss ו-Take-Profit אופטימליים בעזרת AI.
    מחזיר dict: {'stop_loss': float, 'take_profit': float}
    """
    prompt = (
        f"For the symbol {symbol} with entry price {entry_price}, RSI {rsi}, ADX {adx}, trend {trend},\n"
        "suggest optimal stop-loss and take-profit levels."
    )
    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a crypto trading strategist."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.0,
        max_tokens=100
    )
    content = resp.choices[0].message.content
    sl = tp = None
    for line in content.splitlines():
        parts = line.replace(",", "").split()
        for i, word in enumerate(parts):
            if word.lower().startswith("stop") and i+1 < len(parts):
                try:
                    sl = float(parts[i+1])
                except:
                    pass
            if word.lower().startswith("take") and i+1 < len(parts):
                try:
                    tp = float(parts[i+1])
                except:
                    pass
    return {"stop_loss": sl, "take_profit": tp}





