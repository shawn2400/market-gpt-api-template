from flask import Flask, request, jsonify
from flask_cors import CORS
import math

app = Flask(__name__)
CORS(app)

# ברירת מחדל ל-ATR אם לא נמסר
DEFAULT_ATR_SL = 1.5
DEFAULT_ATR_TP = 3.5

saved_trades = []

@app.route('/')
def home():
    return "✅ Market GPT API is running"

@app.route('/auto-sl-tp', methods=['POST'])
def auto_sl_tp():
    data = request.json
    entry = float(data['entry'])
    atr_sl = float(data.get('atr_sl', DEFAULT_ATR_SL))
    atr_tp = float(data.get('atr_tp', DEFAULT_ATR_TP))
    stop = round(entry - (atr_sl * 60), 2)
    tp = round(entry + (atr_tp * 60), 2)
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
    data = request.json
    saved_trades.append(data)
    return jsonify({"status": "✅ טרייד נשמר", "trade": data})

@app.route('/get-trades', methods=['GET'])
def get_trades():
    return jsonify(saved_trades)

@app.route('/clear-trades', methods=['POST'])
def clear_trades():
    saved_trades.clear()
    return jsonify({"status": "🧹 כל הטריידים נמחקו"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


