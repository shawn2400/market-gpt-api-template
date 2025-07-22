from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

user_budget = {"amount": 1000}
saved_trades = []

@app.route('/')
def home():
    return "✅ Market GPT API is running"

@app.route('/auto-sl-tp', methods=['POST'])
def auto_sl_tp():
    data = request.json
    entry = float(data['entry'])
    atr = 60.0
    stop = round(entry - atr * 1.5, 2)
    tp = round(entry + atr * 3.5, 2)
    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"stop": stop, "tp": tp, "rrr": rrr})

@app.route('/analyze-trade', methods=['POST'])
def analyze_trade():
    data = request.json
    entry = float(data['entry'])
    stop = float(data['stop'])
    tp = float(data['tp'])
    rrr = round((tp - entry) / (entry - stop), 2)
    return jsonify({"rrr": rrr})

@app.route('/save-trade', methods=['POST'])
def save_trade():
    saved_trades.append(request.json)
    return jsonify({"status": "saved"})

@app.route('/get-trades', methods=['GET'])
def get_trades():
    return jsonify(saved_trades)

@app.route('/clear-trades', methods=['POST'])
def clear_trades():
    saved_trades.clear()
    return jsonify({"status": "cleared"})

@app.route('/analyze-indicators', methods=['POST'])
def analyze_indicators():
    data = request.json
    symbol = data.get('symbol')
    timeframe = data.get('timeframe')
    return jsonify({
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "pending",
        "message": "Technical indicator analysis will be available soon."
    })

@app.route('/suggest-trades', methods=['GET'])
def suggest_trades():
    sample_trades = [
        {"symbol": "ETHUSDT", "confidence": 92.4, "direction": "long"},
        {"symbol": "SOLUSDT", "confidence": 89.7, "direction": "short"}
    ]
    return jsonify(sample_trades)

@app.route('/set-budget', methods=['POST'])
def set_budget():
    global user_budget
    data = request.json
    amount = float(data.get("amount", 1000))
    user_budget["amount"] = amount
    return jsonify({"status": "budget_set", "amount": amount})

@app.route('/generate-grid', methods=['POST'])
def generate_grid():
    data = request.json
    entry = float(data.get("entry"))
    confidence = float(data.get("confidence", 85))
    grids = 5 if confidence < 90 else 7 if confidence < 95 else 10
    range_pct = 1.5 if confidence < 90 else 2.5 if confidence < 95 else 4
    price_range = entry * (range_pct / 100)
    grid_prices = [
        round(entry - price_range + (2 * price_range / (grids - 1)) * i, 4)
        for i in range(grids)
    ]
    return jsonify({
        "entry": entry,
        "confidence": confidence,
        "grids": grids,
        "range_percent": range_pct,
        "grid_prices": grid_prices
    })

@app.route('/trailing-stop', methods=['POST'])
def trailing_stop():
    data = request.json
    entry = float(data['entry'])
    trail_pct = float(data.get("trail_percent", 1.0)) / 100
    direction = data.get("direction", "long")
    if direction == "long":
        stop = round(entry * (1 - trail_pct), 2)
        tp = round(entry * (1 + trail_pct * 2.5), 2)
    else:
        stop = round(entry * (1 + trail_pct), 2)
        tp = round(entry * (1 - trail_pct * 2.5), 2)
    return jsonify({
        "entry": entry,
        "trail_percent": trail_pct * 100,
        "trailing_stop": stop,
        "trailing_tp": tp,
        "direction": direction
    })

@app.route('/get-chart', methods=['POST'])
def get_chart():
    data = request.json
    symbol = data.get("symbol", "BTCUSDT")
    timeframe = data.get("timeframe", "1h")
    return jsonify({
        "symbol": symbol,
        "timeframe": timeframe,
        "chart_url": f"https://dummyimage.com/600x400/000/fff&text={symbol}+{timeframe}+chart"
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

