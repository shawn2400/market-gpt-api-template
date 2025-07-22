from flask import Flask, request, jsonify
import csv
import time

app = Flask(__name__)
trades = []

@app.route("/")
def home():
    return "Market GPT API is running!"

@app.route("/auto-sl-tp", methods=["POST"])
def auto_sl_tp():
    data = request.json
    symbol = data["symbol"]
    entry = data["entry"]
    atr_sl = data.get("atr_sl", 1.5)
    atr_tp = data.get("atr_tp", 3.5)

    stop = entry - (atr_sl * 10)
    tp = entry + (atr_tp * 10)
    rrr = round((tp - entry) / (entry - stop), 2)

    return jsonify({"symbol": symbol, "entry": entry, "stop": stop, "tp": tp, "rrr": rrr})

@app.route("/analyze-trade", methods=["POST"])
def analyze_trade():
    data = request.json
    entry, stop, tp = data["entry"], data["stop"], data["tp"]
    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"rrr": rrr})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    data = request.json
    trades.append(data)
    return jsonify({"status": "saved", "trade": data})

@app.route("/get-trades")
def get_trades():
    return jsonify(trades)

@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    trades.clear()
    return jsonify({"status": "cleared"})

@app.route("/smart-grid", methods=["POST"])
def smart_grid():
    data = request.json
    entry = data["entry"]
    budget = data["budget"]
    grid_count = 4
    grid_size = round((entry * 0.01), 2)
    price_range = [round(entry - i * grid_size, 2) for i in range(grid_count)]
    return jsonify({"entry": entry, "grid_prices": price_range, "budget": budget})

@app.route("/exit-on-broken-rrr", methods=["POST"])
def exit_on_broken_rrr():
    data = request.json
    cp, entry, stop, tp = data.values()
    if cp < stop:
        return jsonify({"exit": True, "reason": "stop hit"})
    elif cp > tp:
        return jsonify({"exit": True, "reason": "tp hit"})
    else:
        return jsonify({"exit": False, "reason": "RRR intact"})

@app.route("/market-analysis")
def market_analysis():
    symbol = request.args.get("symbol")
    timeframe = request.args.get("timeframe", "24h")
    return jsonify({"symbol": symbol, "timeframe": timeframe, "trend": "up", "volatility": "medium"})

@app.route("/log-csv", methods=["POST"])
def log_csv():
    with open("trades.csv", "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
    return jsonify({"status": "CSV saved"})

@app.route("/time-to-tp", methods=["POST"])
def time_to_tp():
    data = request.json
    distance = abs(data["tp"] - data["entry"])
    hours = round(distance / data["atr"], 2)
    return jsonify({"hours": hours})

@app.route("/daily-volatility")
def daily_volatility():
    symbol = request.args.get("symbol")
    return jsonify({"symbol": symbol, "volatility": "2.3%"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)





