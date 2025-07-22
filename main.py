from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import matplotlib.pyplot as plt
import io, os
import numpy as np
from ta.volatility import AverageTrueRange

app = Flask(__name__)
CORS(app)

trades = []

@app.post("/auto-sl-tp")
def auto_sl_tp():
    data = request.json
    symbol = data.get("symbol")
    entry = float(data.get("entry"))
    atr_sl = float(data.get("atr_sl", 0))
    atr_tp = float(data.get("atr_tp", 0))

    if atr_sl == 0 or atr_tp == 0:
        return jsonify({"error": "ATR must be greater than 0"}), 400

    stop = entry - atr_sl
    tp = entry + atr_tp

    if entry == stop:
        return jsonify({"error": "Stop cannot be equal to entry"}), 400

    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"sl": round(stop, 4), "tp": round(tp, 4), "rrr": rrr})

@app.post("/analyze-trade")
def analyze_trade():
    data = request.json
    entry = float(data.get("entry"))
    stop = float(data.get("stop"))
    tp = float(data.get("tp"))
    if entry == stop:
        return jsonify({"error": "Stop cannot be equal to entry"}), 400

    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"rrr": rrr})

@app.post("/save-trade")
def save_trade():
    data = request.json
    trades.append(data)
    return jsonify({"status": "saved"})

@app.get("/get-trades")
def get_trades():
    return jsonify(trades)

@app.post("/clear-trades")
def clear_trades():
    trades.clear()
    return jsonify({"status": "cleared"})

@app.post("/smart-grid")
def smart_grid():
    data = request.json
    entry = float(data.get("entry"))
    budget = float(data.get("budget"))
    symbol = data.get("symbol")

    atr = 0.5
    grid_size = max(1, round(budget / (atr * 5)))
    price_range = round(atr * 4, 2)

    grid = {
        "symbol": symbol,
        "entry": entry,
        "grids": grid_size,
        "price_range": price_range,
        "per_grid": round(budget / grid_size, 2)
    }
    return jsonify(grid)

@app.post("/exit-on-broken-rrr")
def exit_on_broken_rrr():
    data = request.json
    current = float(data.get("current_price"))
    entry = float(data.get("entry"))
    stop = float(data.get("stop"))
    tp = float(data.get("tp"))

    if current < stop:
        return jsonify({"exit": True, "reason": "Price fell below stop"})
    elif current > tp:
        return jsonify({"exit": False, "reason": "TP already reached"})
    else:
        distance_to_tp = tp - current
        distance_to_sl = current - stop
        if distance_to_sl == 0:
            return jsonify({"exit": True, "reason": "Price near stop"})
        current_rrr = round(distance_to_tp / distance_to_sl, 2)
        if current_rrr < 1:
            return jsonify({"exit": True, "rrr": current_rrr})
        else:
            return jsonify({"exit": False, "rrr": current_rrr})

@app.get("/market-analysis")
def market_analysis():
    symbol = request.args.get("symbol")
    timeframe = request.args.get("timeframe", "24h")
    change = round(np.random.uniform(-5, 5), 2)
    volatility = round(np.random.uniform(1, 10), 2)

    return jsonify({
        "symbol": symbol,
        "timeframe": timeframe,
        "change_percent": change,
        "volatility_percent": volatility
    })

@app.post("/log-csv")
def log_to_csv():
    df = pd.DataFrame(trades)
    df.to_csv("trades.csv", index=False)
    return jsonify({"status": "logged to CSV"})

@app.post("/time-to-tp")
def time_to_tp():
    data = request.json
    entry = float(data.get("entry"))
    tp = float(data.get("tp"))
    atr = float(data.get("atr"))

    if atr == 0:
        return jsonify({"error": "ATR cannot be zero"}), 400

    distance = abs(tp - entry)
    hours = round(distance / atr, 1)
    return jsonify({"estimated_hours": hours})

@app.get("/daily-volatility")
def daily_vol():
    symbol = request.args.get("symbol")
    vol = round(np.random.uniform(2, 8), 2)
    return jsonify({"symbol": symbol, "volatility_percent": vol})

@app.get("/graph-analysis")
def graph_analysis():
    symbol = request.args.get("symbol")
    x = list(range(30))
    prices = [np.random.uniform(1, 2) + i * 0.01 for i in x]
    rsi = [np.random.uniform(30, 70) for _ in x]
    macd = [np.sin(i/5.0)*10 for i in x]

    fig, ax1 = plt.subplots()
    ax1.plot(x, prices, label='Price')
    ax1.set_title(f"Technical Graph for {symbol}")
    ax1.set_ylabel("Price")
    ax1.legend(loc='upper left')

    ax2 = ax1.twinx()
    ax2.plot(x, rsi, color='orange', label='RSI')
    ax2.plot(x, macd, color='green', linestyle='--', label='MACD')
    ax2.set_ylabel("Indicators")
    ax2.legend(loc='upper right')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")







