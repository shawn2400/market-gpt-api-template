# main.py

from flask import Flask, jsonify, request
import requests
import numpy as np
import os
import pandas as pd
from backtest_utils import run_backtest

app = Flask(__name__)

# === שליפת מידע פיוצ'רס מ-Binance ===
def fetch_binance_futures_data(limit=20):
    url = 'https://fapi.binance.com/fapi/v1/ticker/24hr'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        raw_data = response.json()
    except Exception as e:
        raise RuntimeError(f"שגיאה בשליפת מידע מ-Binance: {e}")

    top_symbols = sorted(raw_data, key=lambda x: float(x['quoteVolume']), reverse=True)[:limit]
    results = []

    for item in top_symbols:
        try:
            symbol = item['symbol']
            last_price = float(item['lastPrice'])
            volume = float(item['quoteVolume'])

            # ניתוח טכני רנדומלי זמני (עדיף להחליף לנתוני live)
            rsi = np.random.uniform(20, 80)
            adx = np.random.uniform(10, 50)
            direction = "LONG" if rsi < 30 else "SHORT" if rsi > 70 else "NEUTRAL"

            results.append({
                'symbol': symbol,
                'last_price': last_price,
                'volume': round(volume, 2),
                'rsi': round(rsi, 2),
                'adx': round(adx, 2),
                'direction': direction
            })
        except Exception:
            continue

    return results


# === מסלולי API ===

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "ok",
        "message": "AlgoGPT API is running ✅"
    })


@app.route('/scan', methods=['GET'])
def scan():
    try:
        data = fetch_binance_futures_data(limit=30)
        return jsonify({'results': data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/backtest', methods=['POST'])
def backtest():
    try:
        data = request.get_json()
        prices = data.get("prices", [])
        symbol = data.get("symbol", "UNKNOWN")
        interval = data.get("interval", "15m")

        if not prices or len(prices) < 30:
            return jsonify({
                "error": "Insufficient data – at least 30 candles are required",
                "symbol": symbol,
                "interval": interval,
                "code": "ERR_TOO_SHORT"
            }), 400

        df = pd.DataFrame(prices)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df.dropna(inplace=True)
        if df.empty:
            return jsonify({"error": "No valid rows after cleaning"}), 400

        results = run_backtest(df)
        return jsonify({
            "symbol": symbol,
            "interval": interval,
            "results": results.to_dict(orient="records"),
            "success_count": int(results["success"].sum()),
            "total_trades": len(results),
            "avg_quality": round(results["quality_score"].mean(), 2) if not results.empty else 0
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# === הרצה מקומית בלבד (ל־Render זה לא רלוונטי) ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)























































































































































