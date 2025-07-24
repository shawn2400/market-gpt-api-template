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

@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol")
    return jsonify({"symbol": symbol, "price": 123.45})  # Dummy response

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.get_json()
    entry = data.get("entry")
    stop = data.get("stop")
    target = data.get("target")

    if not all([entry, stop, target]):
        return jsonify({"error": "Missing one of the required fields: entry, stop, target"}), 400

    loss = abs(entry - stop)
    profit = abs(target - entry)
    rrr = round(profit / loss, 2) if loss != 0 else None

    return jsonify({"sl": stop, "tp": target, "rrr": rrr})

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.get_json()
    budget = data.get("budget")
    entry = data.get("entry")
    leverage = data.get("leverage")

    if not all([budget, entry, leverage]):
        return jsonify({"error": "Missing required fields"}), 400

    quantity = round((budget * leverage) / entry, 4)
    return jsonify({"quantity": quantity})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    trade = request.get_json()
    trades.append(trade)
    return jsonify({"message": "Trade saved"})

@app.route("/get-trades", methods=["GET"])
def get_trades():
    return jsonify(trades)

@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    trades.clear()
    return jsonify({"message": "All trades cleared"})

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()

    if not data or "prices" not in data:
        return jsonify({"error": "Missing 'prices' key in JSON"}), 400

    prices = data["prices"]
    df = pd.DataFrame(prices)

    if df.empty or not all(col in df.columns for col in ["open", "high", "low", "close"]):
        return jsonify({"error": "Invalid 'prices' data format"}), 400

    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd_diff()

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

    return jsonify({
        "signal": "buy" if df["rsi"].iloc[-1] < 30 else "sell" if df["rsi"].iloc[-1] > 70 else "neutral",
        "rsi": round(df["rsi"].iloc[-1], 2),
        "macd": round(df["macd"].iloc[-1], 4),
        "chart": f"data:image/png;base64,{image_base64}"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))























