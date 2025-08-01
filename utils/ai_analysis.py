# utils/ai_analysis.py

import os
import re
import openai
from utils.binance_client import client  # or whichever client you use

openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_with_ai(
    symbol: str,
    rsi: float,
    adx: float,
    trend: str,
    pattern: str,
    volume: float
) -> dict:
    """
    Calls OpenAI to get a recommendation based on technical params.
    Returns something like: {'signal':'BUY','confidence':0.87}
    """
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
        upper = line.upper()
        if upper.startswith(("BUY", "SELL", "HOLD")):
            result["signal"] = line
        if "confidence" in line.lower():
            m = re.search(r"(\d+(\.\d+)?)", line)
            if m:
                result["confidence"] = float(m.group(1))

    return result




