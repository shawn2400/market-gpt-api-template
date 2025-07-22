# main.py - Flask API for Market GPT

from flask import Flask, request, jsonify
from flask_cors import CORS
import math
import csv
import os

app = Flask(__name__)
CORS(app)

TRADES_FILE = "trades.csv"

@app.route("/")
def index():
    return "Market GPT API is running"

@app.route("/auto-sl-tp", methods=["POST"])
def auto_sl_tp():
    data = request.get_json()
    symbol = data.get("symbol")
    entry = float(data.get("entry"))
    atr_sl = float(data.get("atr_sl"))
    atr_tp = float(data.get("atr_tp"))

    stop = round(entry - atr_sl * 60, 2)
    tp = round(entry + atr_tp * 60, 2)
    rrr = round((tp - entry) / (entry - stop), 2)

    return jsonify({
        "symbol": symbol,
        "entry": entry,
        "stop": stop,
        "tp": tp,
        "rrr": rrr
    })

@app.route("/analyze-trade", methods=["POST"])
def analyze_trade():
    data = request.get_json()
    entry = float(data["entry"])
    stop = float(data["stop"])
    tp = float(data["tp"])
    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"rrr": rrr})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    data = request.get_json()
    with open(TRADES_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([data["symbol"], data["entry"], data["stop"], data["tp"], data.get("rrr", 0)])
    return jsonify({"status": "success", "message": "Trade saved"})

@app.route("/get-trades", methods=["GET"])
def get_trades():
    trades = []
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, mode="r") as file:
            reader = csv.reader(file)
            for row in reader:
                trades.append({"symbol": row[0], "entry": row[1], "stop": row[2], "tp": row[3], "rrr": row[4]})
    return jsonify(trades)

@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    if os.path.exists(TRADES_FILE):
        os.remove(TRADES_FILE)
    return jsonify({"status": "cleared"})

@app.route("/grid-calc", methods=["POST"])
def grid_calc():
    data = request.get_json()
    symbol = data.get("symbol")
    budget = float(data.get("budget"))
    grid_count = 5
    grid_spacing = 0.25 / 100
    price = float(data.get("entry")) if "entry" in data else 100

    amount_per_grid = budget / grid_count
    grids = [round(price * (1 - i * grid_spacing), 2) for i in range(grid_count)]

    return jsonify({
        "symbol": symbol,
        "budget": budget,
        "grids": grids,
        "amount_per_grid": round(amount_per_grid, 2)
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)



