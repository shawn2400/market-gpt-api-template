import os
import json
import pytz
import uuid
import logging
import traceback
import matplotlib.pyplot as plt
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from snapshot_utils import save_trade_snapshot as generate_snapshot
from report_utils import generate_daily_report_pdf
from news_utils import fetch_crypto_news
from binance.client import Client

app = Flask(__name__)
CORS(app)

# Binance credentials from environment (or hardcoded for Render)
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "your_binance_key_here")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "your_binance_secret_here")
binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

TRADES_FILE = "pnl_tracker.json"

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE, "r") as f:
        return json.load(f)

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

@app.route("/save", methods=["POST"])
def save_trade():
    data = request.json
    trades = load_trades()
    trade_id = str(uuid.uuid4())
    data["id"] = trade_id
    data["timestamp"] = datetime.utcnow().isoformat()
    trades.append(data)
    save_trades(trades)
    return jsonify({"message": "Trade saved", "id": trade_id})

@app.route("/trades", methods=["GET"])
def get_trades():
    return jsonify(load_trades())

@app.route("/clear", methods=["POST"])
def clear_trades():
    save_trades([])
    return jsonify({"message": "All trades cleared"})

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.json
    budget = data.get("budget", 100)
    entry = data.get("entry")
    leverage = data.get("leverage", 10)
    if not entry:
        return jsonify({"error": "Missing entry price"}), 400
    quantity = round((budget * leverage) / entry, 4)
    return jsonify({"quantity": quantity})

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.json
    entry = data.get("entry")
    atr = data.get("atr", 0)
    direction = data.get("direction", "LONG")
    if direction == "LONG":
        sl = round(entry - atr * 1.5, 2)
        tp = round(entry + atr * 3.75, 2)
    else:
        sl = round(entry + atr * 1.5, 2)
        tp = round(entry - atr * 3.75, 2)
    rrr = round(abs(tp - entry) / abs(entry - sl), 2)
    return jsonify({"sl": sl, "tp": tp, "rrr": rrr})

@app.route("/snapshot", methods=["POST"])
def snapshot():
    try:
        data = request.json
        image_base64 = generate_snapshot(data)
        return jsonify({"image": image_base64})
    except Exception as e:
        logging.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/daily-report", methods=["GET"])
def daily_report():
    try:
        report_path = generate_daily_report_pdf()
        return jsonify({"report_path": report_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def news():
    try:
        articles = fetch_crypto_news()
        return jsonify({"news": articles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/execute-trade", methods=["POST"])
def execute_trade():
    try:
        data = request.json
        symbol = data["symbol"]
        side = data["side"]  # BUY or SELL
        quantity = float(data["quantity"])
        price = float(data["price"])
        order_type = data.get("order_type", "LIMIT")

        order = binance_client.futures_create_order(
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            timeInForce="GTC"
        )
        return jsonify({"message": "Trade executed", "order": order})
    except Exception as e:
        logging.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    return "AlgoGPT API is live ✅"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)















































