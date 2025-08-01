# utils/ai_analysis.py

import os
import json
import openai
from typing import Tuple, Dict
from utils.binance_client import client

# Ensure OPENAI_API_KEY is set in environment
openai.api_key = os.getenv("OPENAI_API_KEY")


def analyze_with_ai(
    symbol: str,
    rsi: float,
    adx: float,
    trend: str,
    pattern: str,
    volume: float
) -> Dict[str, float]:
    """
    Perform an AI analysis via OpenAI based on technical parameters.
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
            {"role": "user",   "content": prompt}
        ],
        temperature=0.0,
        max_tokens=150
    )
    content = resp.choices[0].message.content.strip()

    # Basic parsing of response
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    result: Dict[str, float] = {}
    for line in lines:
        upper = line.upper()
        if upper.startswith("BUY") or upper.startswith("SELL") or upper.startswith("HOLD"):
            result["signal"] = line.split()[0]
        if "confidence" in lower := line.lower():
            import re
            match = re.search(r"(\d+(\.\d+)?)", line)
            if match:
                result["confidence"] = float(match.group(1))

    return result


def predict_optimal_sl_tp(
    symbol: str,
    interval: str = "1h",
    lookback: int = 50,
    risk_reward_ratio: float = 1.5
) -> Tuple[float, float]:
    """
    Return (stop_loss, take_profit) based on AI analysis of recent candlesticks.
    """
    # Fetch recent candle data
    klines = client.get_klines(symbol=symbol, interval=interval, limit=lookback)
    closes = [float(k[4]) for k in klines]

    prompt = (
        f"Given the recent {lookback} {interval} closing prices for {symbol}: {closes}, "
        f"recommend optimal stop-loss and take-profit using a risk/reward ratio of {risk_reward_ratio}. "
        "Return JSON with keys 'sl' and 'tp'."
    )

    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=100,
    )
    content = resp.choices[0].message.content.strip()

    try:
        data = json.loads(content)
        sl = float(data["sl"])
        tp = float(data["tp"])
    except Exception as e:
        raise ValueError(f"Failed to parse SL/TP response: {e}\nRaw: {content}")

    return sl, tp

