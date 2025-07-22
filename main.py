from flask import Flask, request, jsonify, send_file
import matplotlib.pyplot as plt
import pandas as pd
import os, io, csv
import numpy as np
from datetime import datetime, timedelta

app = Flask(__name__)

trades = []

@app.route("/auto-sl-tp", methods=["POST"])
def auto_sl_tp():
    data = request.get_json()
    entry = data['entry']
    atr_sl = data.get('atr_sl', 1.0)
    atr_tp = data.get('atr_tp', 2.0)
    stop = round(entry - (entry * atr_sl / 100), 2)
    tp = round(entry + (entry * atr_tp / 100), 2)
    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"stop": stop, "tp": tp, "rrr": rrr})

@app.route("/analyze-trade", methods=["POST"])
def analyze_trade():
    data = request.get_json()
    entry, stop, tp = data['entry'], data['stop'], data['tp']
    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"rrr": rrr})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    trade = request.get_json()
    trades.append(trade)
    return jsonify({"status": "saved", "trade": trade})

@app.route("/get-trades", methods=["GET"])
def get_trades():
    return jsonify(trades)

@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    trades.clear()
    return jsonify({"status": "cleared"})

@app.route("/smart-grid", methods=["POST"])
def smart_grid():
    data = request.get_json()
    entry = data['entry']
    budget = data['budget']
    atr = 1.5
    grid_count = int(min(10, budget / 5))
    grid_range = round(entry * atr / 100, 2)
    grid_levels = [round(entry - (i * grid_range), 2) for i in range(grid_count)]
    return jsonify({"grid_levels": grid_levels, "grid_count": grid_count})

@app.route("/exit-on-broken-rrr", methods=["POST"])
def exit_on_broken_rrr():
    data = request.get_json()
    cp, entry, stop, tp = data['current_price'], data['entry'], data['stop'], data['tp']
    rrr = (tp - entry) / (entry - stop)
    current_rr = (cp - entry) / (entry - stop)
    exit_signal = current_rr < rrr * 0.3
    return jsonify({"exit": exit_signal, "current_rr": round(current_rr,2)})

@app.route("/log-csv", methods=["POST"])
def log_csv():
    filename = "trades.csv"
    with open(filename, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
    return jsonify({"status": "logged", "file": filename})

@app.route("/time-to-tp", methods=["POST"])
def time_to_tp():
    data = request.get_json()
    entry, tp, atr = data['entry'], data['tp'], data['atr']
    price_diff = abs(tp - entry)
    if atr == 0:
        return jsonify({"time_estimate": "Unknown"})
    bars = price_diff / atr
    time_minutes = int(bars * 5)
    return jsonify({"estimated_minutes": time_minutes})

@app.route("/daily-volatility", methods=["GET"])
def daily_volatility():
    symbol = request.args.get('symbol')
    volatility = round(np.random.uniform(2, 5), 2)
    return jsonify({"symbol": symbol, "daily_volatility": f"{volatility}%"})

@app.route("/market-analysis", methods=["GET"])
def market_analysis():
    symbol = request.args.get('symbol')
    timeframe = request.args.get('timeframe', '24h')
    change = round(np.random.uniform(-5, 5), 2)
    volatility = round(np.random.uniform(1, 5), 2)
    return jsonify({"symbol": symbol, "change": f"{change}%", "volatility": f"{volatility}%", "timeframe": timeframe})

@app.route("/graph-analysis", methods=["GET"])
def graph_analysis():
    symbol = request.args.get("symbol", "BTCUSDT")
    prices = np.random.normal(100, 2, 100)
    plt.figure(figsize=(10,4))
    plt.plot(prices, label=symbol)
    plt.title(f"Graph Analysis - {symbol}")
    plt.xlabel("Time")
    plt.ylabel("Price")
    plt.grid(True)
    plt.legend()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)






