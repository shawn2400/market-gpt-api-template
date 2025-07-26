from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import ta
import matplotlib.pyplot as plt
import os
import io
import base64
import hmac
import hashlib
import time
import requests
from datetime import datetime
import pytz

# Binance API Keys (REAL)
BINANCE_API_KEY = "jJnAfHZd0EWQpX0CA0QNxRnrtsrnW10GQMg6Dx8d9O63mZSzZV7ixSBLNEqTeMIh"
BINANCE_API_SECRET = "soQYlzu6jYiQj8ZLxlXNPWHWTLPRb0EXLK239iFVz1XmnX9EvtDaG7D9zGabCVEq"

app = Flask(__name__)
CORS(app)

trades = []
history = []

@app.route("/", methods=["GET"])
def home():
    check = requests.get("https://fapi.binance.com/fapi/v1/time")
    if check.status_code == 200:
        return jsonify({"message": "✅ AlgoGPT API is live (Binance connected)"})
    return jsonify({"message": "⚠️ API live but Binance connection failed"}), 500

@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol")
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
        res = requests.get(url).json()
        return jsonify({"symbol": symbol, "price": float(res["price"])})
    except:
        return jsonify({"symbol": symbol, "price": None, "error": "Price fetch failed"}), 400

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.get_json()
    entry = data.get("entry")
    stop = data.get("stop")
    target = data.get("target") or data.get("tp")
    if entry is None or stop is None or target is None:
        return jsonify({"error": "Missing entry, stop, or target"}), 400
    loss = abs(entry - stop)
    profit = abs(target - entry)
    if loss == 0:
        return jsonify({"error": "Invalid stop loss"}), 400
    rrr = round(profit / loss, 2)
    if rrr < 2.0:
        return jsonify({"error": f"RRR too low: {rrr}"}), 400
    trailing_tp = round(profit * 0.2, 4)
    return jsonify({
        "sl": stop, "tp": target, "rrr": rrr, "trailing_tp": trailing_tp,
        "sl_note": f"(Suggested SL size: {round(loss, 4)})"
    })

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
    required = ["symbol", "entry", "stop", "tp", "leverage", "direction", "confidence", "type", "order_type"]
    if not all(field in trade for field in required):
        return jsonify({"error": "Missing required fields"}), 400

    if len([t for t in trades if t["status"] == "OPEN"]) >= 4:
        return jsonify({"error": "Max 4 trades allowed"}), 400

    trade["type"] = trade["type"].upper()
    trade["order_type"] = trade["order_type"].upper()
    sl_size = abs(trade["entry"] - trade["stop"])
    trade["trailing_sl"] = round(sl_size * 0.2, 4)
    trade["rrr"] = round(abs(trade["tp"] - trade["entry"]) / sl_size, 2)

    if trade["confidence"] < 86:
        return jsonify({"error": "Confidence must be ≥86"}), 400
    if trade["confidence"] < 88 and trade.get("quality_score", 0) < 4:
        return jsonify({"error": "Low confidence without quality score"}), 400
    if trade["confidence"] < 90 and trade["rrr"] < 2.5:
        return jsonify({"error": "RRR too low for confidence"}), 400

    trade["status"] = "OPEN"
    trades.append(trade)
    history.append(trade)
    return jsonify({"message": "Trade saved", "trade": trade})

def execute_trade_internal(data):
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": data["symbol"],
        "side": data["side"].upper(),
        "type": data["order_type"].upper(),
        "quantity": data["quantity"],
        "price": data["price"],
        "recvWindow": 5000,
        "timeInForce": "GTC",
        "timestamp": timestamp
    }
    query = "&".join([f"{k}={params[k]}" for k in sorted(params)])
    signature = hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    url = f"https://api.binance.com/api/v3/order?{query}&signature={signature}"
    res = requests.post(url, headers=headers)
    if res.status_code == 200:
        return jsonify({"message": "Executed", "response": res.json()})
    return jsonify({"error": "Execution failed", "details": res.json()}), 400

@app.route("/save-and-execute", methods=["POST"])
def save_and_execute():
    trade = request.get_json()
    if len([t for t in trades if t["status"] == "OPEN"]) >= 4:
        return jsonify({"error": "Max 4 trades allowed"}), 400

    required = ["symbol", "entry", "stop", "tp", "leverage", "direction", "confidence", "type", "order_type", "quantity"]
    if not all(field in trade for field in required):
        return jsonify({"error": "Missing required fields"}), 400

    sl_size = abs(trade["entry"] - trade["stop"])
    trade["rrr"] = round(abs(trade["tp"] - trade["entry"]) / sl_size, 2)
    trade["trailing_sl"] = round(sl_size * 0.2, 4)
    trade["status"] = "OPEN"

    if trade["confidence"] < 86:
        return jsonify({"error": "Confidence must be ≥86"}), 400
    if trade["confidence"] < 88 and trade.get("quality_score", 0) < 4:
        return jsonify({"error": "Low confidence without quality score"}), 400
    if trade["confidence"] < 90 and trade["rrr"] < 2.5:
        return jsonify({"error": "RRR too low for confidence"}), 400

    trades.append(trade)
    history.append(trade)

    execution_data = {
        "symbol": trade["symbol"],
        "side": "BUY" if trade["direction"] == "LONG" else "SELL",
        "quantity": trade["quantity"],
        "price": trade["entry"],
        "order_type": trade["order_type"]
    }
    return execute_trade_internal(execution_data)

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
            return jsonify({"message": "Trade closed", "trade": trade})
    return jsonify({"error": "No open trade for symbol"}), 404

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    prices = data.get("prices")
    if not prices:
        return jsonify({"error": "Missing 'prices'"}), 400

    df = pd.DataFrame(prices)
    if df.empty or not all(col in df.columns for col in ["open", "high", "low", "close"]):
        return jsonify({"error": "Invalid price data"}), 400

    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"]).rsi()
    df["macd"] = ta.trend.MACD(close=df["close"]).macd_diff()
    df["atr"] = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"]).average_true_range()

    atr = round(df["atr"].iloc[-1], 4)
    close = df["close"].iloc[-1]
    sl = round(close - (1.5 * atr), 4)
    tp = round(close + (2.5 * (close - sl)), 4)

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
        "dynamic_sl": sl,
        "dynamic_tp": tp,
        "chart": f"data:image/png;base64,{image_base64}"
    })

@app.route("/current-time-il", methods=["GET"])
def current_time_il():
    tz = pytz.timezone("Asia/Jerusalem")
    now = datetime.now(tz)
    hour = now.hour
    hot_hours = [(8, 10), (12, 14), (16, 18), (21, 23)]
    is_hot = any(start <= hour <= end for start, end in hot_hours)

    return jsonify({
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "hour": hour,
        "is_hot_hour": is_hot,
        "note": "🟢 שעה חמה למסחר" if is_hot else "🔴 שעה חלשה – עדיף להמתין"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))



































