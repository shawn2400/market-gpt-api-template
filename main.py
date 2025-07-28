from flask import Flask, jsonify, request
import requests
import numpy as np
import os
import pandas as pd
from backtest_utils import run_backtest  # <- זה מוסיף את הפונקציה שלך

app = Flask(__name__)

def fetch_binance_futures_data():
    url = 'https://fapi.binance.com/fapi/v1/ticker/24hr'
    resp = requests.get(url)
    raw_data = resp.json()

    top_20 = sorted(raw_data, key=lambda x: float(x['quoteVolume']), reverse=True)[:20]

    results = []
    for item in top_20:
        symbol = item['symbol']
        last_price = float(item['lastPrice'])
        volume = float(item['quoteVolume'])

        rsi = np.random.uniform(20, 80)
        adx = np.random.uniform(10, 50)
        direction = "LONG" if rsi < 30 else "SHORT" if rsi > 70 else "NEUTRAL"

        results.append({
            'symbol': symbol,
            'last_price': last_price,
            'volume': volume,
            'rsi': round(rsi, 2),
            'adx': round(adx, 2),
            'direction': direction
        })

    return results

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "ok", "message": "AlgoGPT API is running ✅"})

@app.route('/scan', methods=['GET'])
def scan():
    try:
        data = fetch_binance_futures_data()
        return jsonify({'results': data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/backtest', methods=['POST'])
def backtest():
    try:
        data = request.get_json()
        prices = pd.DataFrame(data["prices"])
        results = run_backtest(prices)
        return jsonify(results.to_dict(orient="records"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
















































































































































