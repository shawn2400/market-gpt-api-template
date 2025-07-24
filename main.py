from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------- /analyze ----------------
@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    symbol = data.get('symbol')
    if not symbol:
        return jsonify({"error": "Missing symbol"}), 400

    # סימולציה של ניתוח – כאן תוכל לשלב קריאות ל-Binance API
    result = {
        "symbol": symbol,
        "rsi": "Overbought",
        "macd": "Bullish cross",
        "ema": "Price above EMA50",
        "recommendation": "📈 BUY signal detected"
    }
    return jsonify(result)

# ---------------- /calculate-sl-tp ----------------
@app.route('/calculate-sl-tp', methods=['POST'])
def calculate_sl_tp():
    data = request.get_json()
    entry = data.get('entry')
    stop = data.get('stop')
    target = data.get('target')

    if not all([entry, stop, target]):
        return jsonify({"error": "Missing entry/stop/target"}), 400

    risk = round(entry - stop, 4)
    reward = round(target - entry, 4)
    rrr = round(reward / risk, 2) if risk != 0 else None

    return jsonify({
        "entry": entry,
        "stop": stop,
        "target": target,
        "rrr": rrr,
        "reward_percent": round((reward / entry) * 100, 2),
        "risk_percent": round((risk / entry) * 100, 2)
    })

# ---------------- /calculate-quantity ----------------
@app.route('/calculate-quantity', methods=['POST'])
def calculate_quantity():
    data = request.get_json()
    budget = data.get('budget')
    leverage = data.get('leverage')
    entry = data.get('entry')

    if not all([budget, leverage, entry]):
        return jsonify({"error": "Missing budget/leverage/entry"}), 400

    quantity = round((budget * leverage) / entry, 4)

    return jsonify({
        "quantity": quantity,
        "calculation": f"({budget} × {leverage}) ÷ {entry} = {quantity}"
    })

# ---------------- /save-trade ----------------
trades = []

@app.route('/save-trade', methods=['POST'])
def save_trade():
    data = request.get_json()
    trades.append(data)
    return jsonify({"status": "Trade saved", "trade": data})

# ---------------- /get-trades ----------------
@app.route('/get-trades', methods=['GET'])
def get_trades():
    return jsonify(trades)

# ---------------- /clear-trades ----------------
@app.route('/clear-trades', methods=['POST'])
def clear_trades():
    trades.clear()
    return jsonify({"status": "All trades cleared"})

# ---------------- Run App ----------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)









