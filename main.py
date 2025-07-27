from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import base64
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from prophet import Prophet
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from ta.volume import OnBalanceVolumeIndicator
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange
from datetime import datetime
from report_utils import generate_daily_report
from snapshot_utils import save_trade_snapshot
import requests
import pytz
from trade_executor import execute_trade

app = Flask(__name__)
CORS(app)

@app.route("/", methods=["GET", "HEAD"])
def index():
    return jsonify({"message": "AlgoGPT API is running"}), 200

@app.route("/preset", methods=["GET"])
def get_preset():
    try:
        with open("preset.txt", "r", encoding="utf-8") as file:
            preset_text = file.read()
        return jsonify({"preset": preset_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/strategy", methods=["GET"])
def get_strategy():
    try:
        with open("preset.txt", "r", encoding="utf-8") as file:
            strategy_text = file.read()
        return jsonify({"strategy": strategy_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.json
    try:
        budget = data["budget"]
        entry = data["entry"]
        leverage = data["leverage"]
        quantity = round((budget * leverage) / entry, 6)
        return jsonify({"quantity": quantity})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sl_tp", methods=["POST"])
def calculate_sl_tp():
    data = request.json
    try:
        entry = float(data["entry"])
        stop = float(data["stop"])
        tp = float(data["tp"])
        risk = abs(entry - stop)
        reward = abs(tp - entry)
        rrr = round(reward / risk, 2)
        return jsonify({"rrr": rrr})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/save", methods=["POST"])
def save_trade():
    data = request.json
    try:
        with open("trades.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        save_trade_snapshot(data)
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/trades", methods=["GET"])
def get_trades():
    try:
        if not os.path.exists("trades.json"):
            return jsonify({"trades": []})
        with open("trades.json", "r", encoding="utf-8") as f:
            lines = f.readlines()
            trades = [json.loads(line) for line in lines]
        return jsonify({"trades": trades})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/clear", methods=["POST"])
def clear_trades():
    try:
        open("trades.json", "w", encoding="utf-8").close()
        return jsonify({"status": "cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/daily-report", methods=["GET"])
def daily_report():
    try:
        if not os.path.exists("pnl_tracker.json"):
            return jsonify({"error": "No statistics file found"}), 400
        pdf_base64 = generate_daily_report()
        return jsonify({"pdf_base64": pdf_base64})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ai-analyze", methods=["POST"])
def ai_analyze():
    try:
        data = request.json
        df = pd.DataFrame(data["prices"])
        df["time"] = pd.to_datetime(df["time"])
        df.rename(columns={"time": "ds", "close": "y"}, inplace=True)
        model = Prophet()
        model.fit(df)
        future = model.make_future_dataframe(periods=10)
        forecast = model.predict(future)
        fig = model.plot(forecast)
        filename = "forecast.png"
        fig.savefig(filename)
        with open(filename, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        direction = "LONG" if forecast["yhat"].iloc[-1] > df["y"].iloc[-1] else "SHORT"
        return jsonify({
            "symbol": data["symbol"],
            "direction": direction,
            "forecast": forecast[["ds", "yhat"]].tail(10).to_dict(orient="records"),
            "chart": img_data
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def get_news():
    try:
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": "89404de8e0bb4d6e78e95ed26ff19970cdb8830a",
            "public": "true"
        }
        response = requests.get(url, params=params)
        news_data = response.json().get("results", [])
        return jsonify({"news": news_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stats", methods=["GET"])
def get_stats():
    try:
        if not os.path.exists("pnl_tracker.json"):
            return jsonify({"error": "No statistics available"}), 400
        df = pd.read_json("pnl_tracker.json")
        df["date"] = pd.to_datetime(df["timestamp"]).dt.date
        stats = df.groupby("date").agg({
            "pnl": ["sum", "count"],
            "success": "mean"
        }).reset_index()
        stats.columns = ["date", "total_pnl", "num_trades", "success_rate"]
        stats["success_rate"] = (stats["success_rate"] * 100).round(2)
        stats["total_pnl"] = stats["total_pnl"].round(2)
        return jsonify({"daily_stats": stats.to_dict(orient="records")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/execute-trade", methods=["POST"])
def execute():
    try:
        data = request.json
        symbol = data["symbol"]
        side = data["side"]
        quantity = data["quantity"]
        price = data.get("price")
        order_type = data.get("order_type", "LIMIT")
        market_type = data.get("market_type", "futures")

        result = execute_trade(symbol, side, quantity, price, order_type, market_type)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)











































































































