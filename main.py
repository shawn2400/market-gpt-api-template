from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from ta import add_all_ta_features
from prophet import Prophet
from fpdf import FPDF
import schedule
import pytz
import datetime
import json
import os
import base64
from io import BytesIO

from snapshot_utils import generate_snapshot
from report_utils import generate_daily_report
from news_utils import fetch_crypto_news, analyze_news_impact, send_email_alert

app = Flask(__name__)
CORS(app)

# === מסלולים קיימים ===

@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol", "BTCUSDT")
    return jsonify({"price": 29500.0, "symbol": symbol})  # דמו בלבד

@app.route("/sl_tp", methods=["POST"])
def calculate_sl_tp():
    data = request.get_json()
    entry = float(data["entry"])
    stop = float(data["stop"])
    tp = float(data["tp"])
    rrr = round(abs((tp - entry) / (entry - stop)), 2)
    return jsonify({"entry": entry, "stop": stop, "tp": tp, "RRR": rrr})

@app.route("/save", methods=["POST"])
def save_trade():
    trade = request.get_json()
    try:
        with open("trades.json", "r") as f:
            trades = json.load(f)
    except FileNotFoundError:
        trades = []
    trades.append(trade)
    with open("trades.json", "w") as f:
        json.dump(trades, f, indent=2)
    return jsonify({"message": "Trade saved", "trade": trade})

@app.route("/trades", methods=["GET"])
def get_trades():
    try:
        with open("trades.json", "r") as f:
            trades = json.load(f)
    except FileNotFoundError:
        trades = []
    return jsonify(trades)

@app.route("/clear", methods=["POST"])
def clear_trades():
    with open("trades.json", "w") as f:
        json.dump([], f)
    return jsonify({"message": "All trades cleared"})

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.get_json()
    budget = data.get("budget")
    entry = data.get("entry")
    leverage = data.get("leverage", 20)

    if not budget or not entry:
        return jsonify({"error": "Missing parameters"}), 400

    quantity = round((float(budget) * float(leverage)) / float(entry), 3)
    return jsonify({"quantity": quantity})

@app.route("/snapshot", methods=["POST"])
def get_snapshot():
    data = request.get_json()
    symbol = data.get("symbol")
    prices = data.get("prices")
    image_base64 = generate_snapshot(symbol, prices)
    return jsonify({"image": image_base64})

@app.route("/daily-report", methods=["GET"])
def daily_report():
    report_path = generate_daily_report()
    return jsonify({"report": report_path})

@app.route("/news", methods=["GET"])
def news_analysis():
    news = fetch_crypto_news()
    impact = analyze_news_impact(news)
    if impact["level"] == "high":
        send_email_alert(impact)
    return jsonify(impact)

@app.route("/ai-analyze", methods=["POST"])
def ai_analyze():
    data = request.get_json()
    symbol = data.get("symbol")
    prices = data.get("prices")

    if not symbol or not prices:
        return jsonify({"error": "Missing symbol or prices"}), 400

    try:
        df = pd.DataFrame(prices)
        df['ds'] = pd.to_datetime(df['time'])
        df['y'] = df['close']

        model = Prophet()
        model.fit(df[['ds', 'y']])
        future = model.make_future_dataframe(periods=12, freq='H')
        forecast = model.predict(future)

        direction = "LONG" if forecast["yhat"].iloc[-1] > df['y'].iloc[-1] else "SHORT"

        fig = model.plot(forecast)
        plt.title(f"Forecast for {symbol}")
        plt.xlabel("Time")
        plt.ylabel("Price")
        plt.tight_layout()

        img_buffer = BytesIO()
        plt.savefig(img_buffer, format="png")
        img_buffer.seek(0)
        image_base64 = base64.b64encode(img_buffer.read()).decode("utf-8")

        forecast_out = forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(12).to_dict(orient="records")

        return jsonify({
            "symbol": symbol,
            "direction": direction,
            "forecast": forecast_out,
            "chart": image_base64
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/preset", methods=["GET"])
def get_preset():
    try:
        with open("preset.txt", "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"preset": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/strategy", methods=["GET"])
def get_strategy():
    try:
        with open("preset.txt", "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"strategy": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stats", methods=["GET"])
def get_stats():
    try:
        with open("pnl_tracker.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return jsonify({"message": "No data yet"}), 404

    total_trades = len(data)
    wins = [x for x in data if x.get("pnl", 0) > 0]
    losses = [x for x in data if x.get("pnl", 0) <= 0]
    total_pnl = round(sum([x.get("pnl", 0) for x in data]), 2)

    stats = {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "success_rate": round((len(wins) / total_trades) * 100, 2) if total_trades else 0,
        "total_pnl": total_pnl
    }
    return jsonify(stats)

# ========== הרצה ==========
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)














































