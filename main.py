from flask import Flask, request, jsonify
from flask_cors import CORS
from binance.client import Client
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from fpdf import FPDF
import schedule
import pytz
import datetime
import requests
import io
import base64
from ta.volatility import AverageTrueRange
from ta.trend import MACD, EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from prophet import Prophet
import plotly.graph_objs as go
import threading

# === Flask App ===
app = Flask(__name__)
CORS(app)

# === Binance Client ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "YOUR_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "YOUR_API_SECRET")
binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"message": "AlgoGPT API is running"})

@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol", "BTCUSDT")
    try:
        price = binance_client.get_symbol_ticker(symbol=symbol)
        return jsonify(price)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.json
    try:
        budget = data['budget']
        entry = data['entry']
        leverage = data['leverage']
        quantity = round((budget * leverage) / entry, 4)
        return jsonify({"quantity": quantity})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.json
    try:
        df = pd.DataFrame(data['prices'])
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        atr = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        last_close = df['close'].iloc[-1]
        sl = round(last_close - atr.iloc[-1]*1.5, 2)
        tp = round(last_close + (last_close - sl)*2.5, 2)
        return jsonify({"entry": last_close, "sl": sl, "tp": tp})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/save-trade", methods=["POST"])
def save_trade():
    data = request.json
    try:
        trade = {
            "symbol": data['symbol'],
            "entry": data['entry'],
            "stop": data['stop'],
            "tp": data['tp'],
            "leverage": data['leverage'],
            "direction": data['direction'],
            "type": data.get('type', 'LIMIT'),
            "confidence": data.get('confidence', 90),
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        if not os.path.exists("saved_trades.json"):
            with open("saved_trades.json", "w") as f:
                f.write("[]")
        existing = pd.read_json("saved_trades.json")
        updated = existing.append(trade, ignore_index=True)
        updated.to_json("saved_trades.json", orient="records")
        return jsonify({"message": "Trade saved."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/execute-trade", methods=["POST"])
def execute_trade():
    data = request.json
    try:
        symbol = data['symbol']
        quantity = data['quantity']
        side = Client.SIDE_BUY if data['direction'].upper() == "LONG" else Client.SIDE_SELL
        order_type = Client.ORDER_TYPE_LIMIT
        price = str(data['entry'])

        order = binance_client.create_order(
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            timeInForce=Client.TIME_IN_FORCE_GTC
        )
        return jsonify(order)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)



















































