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
    return jsonify({"symbol": symbol, "price": 123.45})  # Stub price

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.get_json()
    entry = data.get("entry")
    stop = data.get("stop")
    target = data.get("target") or data.get("tp")
    if entry is None or stop is None or target is None:
        return jsonify({"error": "Missing entry, stop or target"}), 400
    loss = abs(entry - stop)
    profit = abs(target - entry)
    if loss == 0:
        return jsonify({"error": "Stop loss must differ from entry"}), 400
    rrr = round(profit / loss, 2)
    if rrr < 2.0:
        return jsonify({"error": f"RRR too low: {rrr}"}), 400
    trailing = round(profit * 0.2, 4)
    return jsonify({"sl": stop, "tp": target, "rrr": rrr, "trailing_tp": trailing})

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.get_json()
    budget = data.get("budget")
    entry = data.get("entry")
    leverage = data.get("leverage")
    if not all([budget, entry, leverage]):
        return jsonify({"error": "Missing fields"}), 400
    if leverage < 5 or leverage > 35:
        return jsonify({"error": "Leverage must be 5×–35×"}), 400
    qty = round((budget * leverage) / entry, 4)
    return jsonify({"quantity": qty})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    trade = request.get_json()
    fields = ["symbol", "entry", "stop", "tp", "leverage", "direction", "confidence", "type", "order_type"]
    if not all(f in trade for f in fields):
        return jsonify({"error": "Missing fields"}), 400
    trade["type"] = trade["type"].upper()
    trade["order_type"] = trade["order_type"].upper()
    if trade["type"] not in ["REGULAR", "GRID"] or trade["order_type"] not in ["LIMIT", "STOP_LIMIT"]:
        return jsonify({"error": "Invalid trade type/order type"}), 400
    sl_size = abs(trade["entry"] - trade["stop"])
    trade["trailing_sl"] = round(sl_size * 0.2, 4)
    if trade["confidence"] < 86:
        return jsonify({"error": "Confidence must be ≥86"}), 400
    if trade["confidence"] < 88 and trade.get("quality_score", 0) < 4:
        return jsonify({"error": "Quality score required for confidence <88"}), 400
    if trade["confidence"] < 90 and trade.get("rrr", 0) < 2.5:
        return jsonify({"error": "RRR too low for confidence <90"}), 400
    trade["status"] = "OPEN"
    trades.append(trade)
    history.append(trade)  # Auto-Risk Allocation – future use
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
    for t in trades:
        if t.get("status") == "OPEN":
            return jsonify({"active": True, "trade": t})
    return jsonify({"active": False})

@app.route("/update-trade", methods=["POST"])
def update_trade():
    symbol = request.get_json().get("symbol")
    for t in trades:
        if t["symbol"] == symbol and t["status"] == "OPEN":
            t["status"] = "CLOSED"
            return jsonify({"message": "Trade updated", "trade": t})
    return jsonify({"error": "Trade not found"}), 404

@app.route("/backtest", methods=["POST"])
def backtest():
    data = request.get_json()
    if "prices" not in data:
        return jsonify({"error": "Missing 'prices'"}), 400
    df = pd.DataFrame(data["prices"])
    if df.empty or not all(c in df.columns for c in ["open", "high", "low", "close"]):
        return jsonify({"error": "Invalid format"}), 400
    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd_diff()
    df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range()
    valid_trades = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        if row["rsi"] < 30 and row["macd"] > 0:
            e = row["close"]
            sl = e - (1.5 * row["atr"])
            tp = e + (2.5 * (e - sl))
            rrr = round((tp - e) / (e - sl), 2)
            if rrr >= 2.5:
                valid_trades.append({"entry": round(e, 4), "sl": round(sl, 4), "tp": round(tp, 4), "rrr": rrr})
    return jsonify({"total": len(df), "valid_trades": valid_trades})

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    if "prices" not in data:
        return jsonify({"error": "Missing prices"}), 400
    df = pd.DataFrame(data["prices"])
    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd_diff()
    df["atr"] = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range()
    close = df["close"].iloc[-1]
    atr = df["atr"].iloc[-1]
    sl = round(close - (1.5 * atr), 4)
    tp = round(close + (2.5 * (close - sl)), 4)
    df_1h = df.tail(60)
    rsi_1h = round(ta.momentum.RSIIndicator(close=df_1h["close"]).rsi().iloc[-1], 2)
    plt.figure(figsize=(10, 4))
    plt.plot(df["close"], label="Close")
    plt.title("RSI & MACD")
    plt.legend()
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    img = base64.b64encode(buf.read()).decode("utf-8")
    plt.close()
    signal = "buy" if df["rsi"].iloc[-1] < 30 else "sell" if df["rsi"].iloc[-1] > 70 else "neutral"
    return jsonify({
        "signal": signal,
        "rsi_15m": round(df["rsi"].iloc[-1], 2),
        "rsi_1h": rsi_1h,
        "macd": round(df["macd"].iloc[-1], 4),
        "atr": round(atr, 4),
        "dynamic_sl": sl,
        "dynamic_tp": tp,
        "chart": f"data:image/png;base64,{img}"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))





























