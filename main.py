from flask import Flask, request, jsonify
from flask_cors import CORS
from binance.client import Client
from datetime import datetime
from ta import trend, momentum, volatility
from report_utils import generate_daily_report
from snapshot_utils import save_trade_snapshot
import pandas as pd
import json
import os

app = Flask(__name__)
CORS(app)

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

TRADES_FILE = "pnl_tracker.json"

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

@app.route("/save", methods=["POST"])
def save_trade():
    data = request.json
    trades = load_trades()
    trades.append(data)
    save_trades(trades)
    save_trade_snapshot(data)
    return jsonify({"status": "saved", "count": len(trades)})

@app.route("/trades", methods=["GET"])
def get_trades():
    trades = load_trades()
    return jsonify(trades)

@app.route("/clear", methods=["POST"])
def clear_trades():
    save_trades([])
    return jsonify({"status": "cleared"})

@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol")
    ticker = client.get_symbol_ticker(symbol=symbol)
    return jsonify(ticker)

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.json
    entry = data["entry"]
    stop = data["stop"]
    tp = data["tp"]
    risk = abs(entry - stop)
    reward = abs(tp - entry)
    rrr = round(reward / risk, 2) if risk > 0 else None
    return jsonify({
        "entry": entry,
        "stop": stop,
        "tp": tp,
        "RRR": rrr
    })

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.json
    budget = data["budget"]
    entry = data["entry"]
    leverage = data["leverage"]
    qty = round((budget * leverage) / entry, 3)
    return jsonify({
        "budget": budget,
        "entry": entry,
        "leverage": leverage,
        "quantity": qty
    })

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    prices = data["prices"]
    df = pd.DataFrame(prices)
    df["ema9"] = trend.ema_indicator(df["close"], window=9)
    df["rsi"] = momentum.rsi(df["close"], window=14)
    df["macd"] = trend.macd_diff(df["close"])
    df["atr"] = volatility.average_true_range(df["high"], df["low"], df["close"])
    latest = df.iloc[-1].to_dict()
    return jsonify(latest)

@app.route("/snapshot", methods=["GET"])
def snapshot():
    if not os.path.exists("snapshots"):
        return jsonify({"error": "No snapshots found"}), 404
    files = os.listdir("snapshots")
    return jsonify({"snapshots": files})

@app.route("/daily-report", methods=["GET"])
def daily_report():
    pdf_path = generate_daily_report()
    return jsonify({"report": pdf_path})

@app.route("/stats", methods=["GET"])
def stats():
    trades = load_trades()
    if not trades:
        return jsonify({"message": "No trades found"})
    total = len(trades)
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    win_rate = round(len(wins) / total * 100, 2) if total > 0 else 0
    profit = sum([t.get("pnl", 0) for t in wins])
    loss = sum([t.get("pnl", 0) for t in losses])
    net = profit + loss
    return jsonify({
        "total_trades": total,
        "win_rate": win_rate,
        "total_profit": round(profit, 2),
        "total_loss": round(loss, 2),
        "net_pnl": round(net, 2)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
















































