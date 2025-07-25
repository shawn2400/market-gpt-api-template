from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import ta
import matplotlib.pyplot as plt
import os
import io
import base64

app = Flask(__name__)
CORS(app)

trades = []
history = []

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "AlgoGPT API is live ✅"})

@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol")
    return jsonify({"symbol": symbol, "price": 123.45})

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.get_json()
    entry = data.get("entry")
    stop = data.get("stop")
    target = data.get("target") or data.get("tp")

    if entry is None or stop is None or target is None:
        return jsonify({"error": "Missing one of the required fields: entry, stop, target/tp"}), 400

    loss = abs(entry - stop)
    profit = abs(target - entry)
    if loss == 0:
        return jsonify({"error": "Stop loss must be different from entry"}), 400

    rrr = round(profit / loss, 2)
    if rrr < 2.0:
        return jsonify({"error": f"RRR too low: {rrr}. Must be ≥ 2.0"}), 400

    trailing_tp = round(profit * 0.2, 4)
    return jsonify({"sl": stop, "tp": target, "rrr": rrr, "trailing_tp": trailing_tp})

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.get_json()
    budget = data.get("budget")
    entry = data.get("entry")
    leverage = data.get("leverage")

    if not all([budget, entry, leverage]):
        return jsonify({"error": "Missing required fields"}), 400

    if leverage < 5 or leverage > 35:
        return jsonify({"error": "Leverage must be between 5× and 35×"}), 400

    quantity = round((budget * leverage) / entry, 4)
    return jsonify({"quantity": quantity})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    trade = request.get_json()
    required_fields = ["symbol", "entry", "stop", "tp", "leverage", "direction", "confidence", "type", "order_type"]
    if not all(field in trade for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    trade_type = trade.get("type", "REGULAR").upper()
    if trade_type not in ["REGULAR", "GRID"]:
        return jsonify({"error": "Invalid trade type. Must be 'REGULAR' or 'GRID'"}), 400

    order_type = trade.get("order_type", "LIMIT").upper()
    if order_type not in ["LIMIT", "STOP_LIMIT"]:
        return jsonify({"error": "Invalid order type. Must be 'LIMIT' or 'STOP_LIMIT'"}), 400

    trade["type"] = trade_type
    trade["order_type"] = order_type

    sl_size = abs(trade["entry"] - trade["stop"])
    trade["trailing_sl"] = round(sl_size * 0.2, 4)

    if trade["confidence"] < 86:
        return jsonify({"error": "Confidence must be ≥86% to save trade"}), 400
    if trade["confidence"] < 88 and trade.get("quality_score", 0) < 4:
        return jsonify({"error": "Confidence <88% allowed only with quality score ≥4"}), 400
    if trade["confidence"] < 90 and trade["rrr"] < 2.5:
        return jsonify({"error": "RRR too low for confidence <90%"}), 400

    trade["status"] = "OPEN"
    trades.append(trade)
    history.append(trade)
    return jsonify({"message": "Trade saved", "trade": trade})

@app.route("/get-trades", methods=["GET"])
def get_trades():
    return jsonify(trades)

@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    trades.clear()
    return jsonify({"message": "All trades cleared"})

@app.route("/active-trade", methods=["GET"])
def active_trade():
    for trade in trades:
        if trade.get("status") == "OPEN":
            return jsonify({"active": True, "trade": trade})
    return jsonify({"active": False})

@app.route("/update-trade", methods=["POST"])
def update_trade():
    data = request.get_json()
    symbol = data.get("symbol")

    for trade in trades:
        if trade.get("symbol") == symbol and trade.get("status") == "OPEN":
            trade["status"] = "CLOSED"
            return jsonify({"message": "Trade updated to CLOSED", "trade": trade})
    return jsonify({"error": "No open trade found for given symbol"}), 404

@app.route("/backtest", methods=["POST"])
def backtest():
    data = request.get_json()
    if not data or "prices" not in data:
        return jsonify({"error": "Missing 'prices' key in JSON"}), 400

    prices = data["prices"]
    df = pd.DataFrame(prices)
    required_cols = ["open", "high", "low", "close"]
    if df.empty or not all(col in df.columns for col in required_cols):
        return jsonify({"error": "Invalid 'prices' data format"}), 400

    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd_diff()
    df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"]).average_true_range()

    valid_trades = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        if row["rsi"] < 30 and row["macd"] > 0:
            entry = row["close"]
            sl = entry - (1.5 * row["atr"])
            tp = entry + (2.5 * (entry - sl))
            rrr = round((tp - entry) / (entry - sl), 2)
            if rrr >= 2.5:
                valid_trades.append({
                    "entry": round(entry, 4),
                    "sl": round(sl, 4),
                    "tp": round(tp, 4),
                    "rrr": rrr
                })

    return jsonify({"total": len(prices), "valid_trades": valid_trades})

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    if not data or "prices" not in data:
        return jsonify({"error": "Missing 'prices' key in JSON"}), 400

    prices = data["prices"]
    df = pd.DataFrame(prices)
    required_cols = ["open", "high", "low", "close"]
    if df.empty or not all(col in df.columns for col in required_cols):
        return jsonify({"error": "Invalid 'prices' data format"}), 400

    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd_diff()
    df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"]).average_true_range()

    atr = round(df["atr"].iloc[-1], 4)
    close_price = df["close"].iloc[-1]
    stop_loss = round(close_price - (1.5 * atr), 4)
    take_profit = round(close_price + (2.5 * (close_price - stop_loss)), 4)

    df_1h = df.tail(60)
    rsi_1h = round(ta.momentum.RSIIndicator(close=df_1h["close"]).rsi().iloc[-1], 2)

    plt.figure(figsize=(10, 4))
    plt.plot(df["close"], label="Close Price")
    plt.title("Price with RSI & MACD")
    plt.legend()
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close()

    signal = "neutral"
    if df["rsi"].iloc[-1] < 30:
        signal = "buy"
    elif df["rsi"].iloc[-1] > 70:
        signal = "sell"

    return jsonify({
        "signal": signal,
        "rsi_15m": round(df["rsi"].iloc[-1], 2),
        "rsi_1h": rsi_1h,
        "macd": round(df["macd"].iloc[-1], 4),
        "atr": atr,
        "dynamic_sl": stop_loss,
        "dynamic_tp": take_profit,
        "chart": f"data:image/png;base64,{image_base64}"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))































