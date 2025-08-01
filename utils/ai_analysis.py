# utils/ai_analysis.py

import os
import openai
from utils.binance_client import client

# Ensure OPENAI_API_KEY is set
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
    Performs an AI analysis call to OpenAI based on technical parameters.
    Returns a dict like {'signal': 'BUY', 'confidence': 0.87}.
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
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
        max_tokens=150
    )

    content = resp.choices[0].message.content
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    result = {}
    import re
    for line in lines:
        upper = line.upper()
        if upper.startswith("BUY") or upper.startswith("SELL") or upper.startswith("HOLD"):
            result["signal"] = line
        if "confidence" in line.lower():
            match = re.search(r"(\d+(\.\d+)?)", line)
            if match:
                result["confidence"] = float(match.group(1))
    return result


def predict_optimal_sl_tp(symbol: str, text_analysis: dict) -> dict:
    """
    Placeholder for predicting optimal stop-loss and take-profit using AI.
    Returns a dict like {'stop_loss': price, 'take_profit': price}.
    """
    # TODO: implement based on text_analysis, e.g., another OpenAI call
    return {}



