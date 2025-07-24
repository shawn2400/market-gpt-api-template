from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import pandas as pd
import ta
import os

app = Flask(__name__)
CORS(app)

BINANCE_BASE_URL = "https://api.binance.com"

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    symbol = data.get('symbol')
    if not symbol:
        return jsonify({"error": "Missing symbol"}), 400

    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": "15m",
        "limit": 100
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return jsonify({"error": f"Binance API error: {response.status_code}"}), 500

        klines = response.json()
        df = pd.DataFrame(klines, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['close'] = df['close'].astype(float)

        # חישוב אינדיקטורים
        df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
        df['ema20'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
        df['ema50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()

        rsi = round(df['rsi'].iloc[-1], 2)
        ema20 = round(df['ema20'].iloc[-1], 4)
        ema50 = round(df['ema50'].iloc[-1], 4)
        price = round(df['close'].iloc[-1], 4)

        signal = "⏸️ ניטרלי"
        if rsi > 70:
            signal = "📉 SELL – RSI Overbought"
        elif rsi < 30:
            signal = "📈 BUY – RSI Oversold"
        elif price > ema20 and price > ema50:
            signal = "📈 BUY – price above EMA20/50"
        elif price < ema20 and price < ema50:
            signal = "📉 SELL – price below EMA20/50"

        return jsonify({
            "symbol": symbol,
            "price": price,
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "recommendation": signal
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

trades = []

@app.route('/save-trade', methods=['POST'])
def save_trade():
    data = request.get_json()
    trades.append(data)
    return jsonify({"status": "Trade saved", "trade": data})

@app.route('/get-trades', methods=['GET'])
def get_trades():
    return jsonify(trades)

@app.route('/clear-trades', methods=['POST'])
def clear_trades():
    trades.clear()
    return jsonify({"status": "All trades cleared"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)










