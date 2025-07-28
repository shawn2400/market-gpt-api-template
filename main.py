# main.py (גרסה משודרגת מלאה)

from flask import Flask, jsonify, request
import os
import pandas as pd
from dotenv import load_dotenv

# === Utils / Services ===
from backtest_utils import run_backtest
from news_utils import fetch_crypto_news, analyze_news_impact
from utils.quantity_utils import calculate_quantity
from utils.sl_tp_utils import calculate_sl_tp
from utils.trade_storage import save_trade
from snapshot_utils import save_trade_snapshot

load_dotenv()

app = Flask(__name__)

# === בסיס API ===
@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "ok",
        "message": "AlgoGPT API is running ✅"
    })

# === סריקת שוק ===
from utils.klines_utils import get_klines
from utils.live_price import get_live_price

def fetch_binance_futures_data(limit=30):
    import requests, numpy as np
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

            # 🔧 סימולציה זמנית עד שתשלב אינדיקטורים חיים
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

@app.route('/scan', methods=['GET'])
def scan():
    try:
        data = fetch_binance_futures_data(limit=30)
        return jsonify({'results': data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === חישוב SL/TP ===
@app.route('/sl_tp', methods=['POST'])
def sl_tp():
    try:
        data = request.get_json()
        df = pd.DataFrame(data.get("df", []))
        direction = data.get("direction")
        result = calculate_sl_tp(df, direction)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === חישוב כמות למסחר ===
@app.route('/calculate-quantity', methods=['POST'])
def calc_qty():
    try:
        data = request.get_json()
        symbol = data['symbol']
        price = data['price']
        leverage = data['leverage']
        budget = data['budget']
        quantity = calculate_quantity(symbol, price, leverage, budget)
        return jsonify({"quantity": quantity})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# === ניתוח חדשות ===
@app.route('/news', methods=['GET'])
def news():
    return jsonify(fetch_crypto_news())

@app.route('/analyze-news', methods=['GET'])
def analyze_news():
    news = fetch_crypto_news()
    return jsonify(analyze_news_impact(news))

# === Backtest ===
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

# === הרצה מקומית בלבד ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
























































































































































