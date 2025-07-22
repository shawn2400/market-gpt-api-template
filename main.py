from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

trades = []

@app.route("/")
def home():
    return "Market GPT API is running"

@app.route("/auto-sl-tp", methods=["POST"])
def auto_sl_tp():
    data = request.json
    symbol = data.get("symbol")
    entry = data.get("entry")
    atr_sl = data.get("atr_sl", 1.0)
    atr_tp = data.get("atr_tp", 2.0)

    stop = round(entry - (atr_sl * 10), 2)
    tp = round(entry + (atr_tp * 10), 2)
    rrr = round((tp - entry) / (entry - stop), 2)

    return jsonify({"symbol": symbol, "entry": entry, "stop": stop, "tp": tp, "rrr": rrr})

@app.route("/analyze-trade", methods=["POST"])
def analyze_trade():
    data = request.json
    entry = data.get("entry")
    stop = data.get("stop")
    tp = data.get("tp")
    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"rrr": rrr})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    trade = request.json
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
    data = request.json
    symbol = data.get("symbol")
    entry = data.get("entry")
    budget = data.get("budget")
    grids = []
    step = entry * 0.003  # 0.3%
    size = round(budget / 5, 2)
    for i in range(5):
        price = round(entry - (i * step), 2)
        grids.append({"price": price, "amount": size})
    return jsonify({"symbol": symbol, "entry": entry, "budget": budget, "grids": grids})

@app.route("/exit-on-broken-rrr", methods=["POST"])
def exit_on_broken_rrr():
    data = request.json
    current_price = data.get("current_price")
    entry = data.get("entry")
    stop = data.get("stop")
    tp = data.get("tp")
    initial_rrr = abs((tp - entry) / (entry - stop))
    live_rrr = abs((tp - current_price) / (current_price - stop))
    broken = live_rrr < 1
    return jsonify({"initial_rrr": initial_rrr, "live_rrr": live_rrr, "broken": broken})

@app.route("/market-analysis", methods=["GET"])
def market_analysis():
    symbol = request.args.get("symbol")
    timeframe = request.args.get("timeframe", "24h")
    # Simulated data
    data = {
        "symbol": symbol,
        "timeframe": timeframe,
        "change": "+2.5%",
        "volatility": "Medium",
        "trend": "Bullish",
        "chart_url": f"https://dummyimage.com/600x400/000/fff&text={symbol}+{timeframe}"
    }
    return jsonify(data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)




