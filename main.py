from flask import Flask, request, jsonify
from flask_cors import CORS
from binance.client import Client
from binance.enums import *
import pandas as pd
import numpy as np
import ta
import hmac, hashlib, time
import requests
import os
import pytz

app = Flask(__name__)
CORS(app)

# === Binance API Keys ===
BINANCE_API_KEY = 'YOUR_API_KEY'
BINANCE_SECRET_KEY = 'YOUR_SECRET_KEY'

client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# === Utility: Get Futures Symbols ===
def get_futures_symbols():
    info = client.futures_exchange_info()
    return [s['symbol'] for s in info['symbols'] if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']

# === Utility: Get Historical Prices ===
def get_klines(symbol, interval='15m', limit=100):
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close',
        'volume', 'close_time', 'quote_asset_volume',
        'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['open'] = df['open'].astype(float)
    return df

# === Utility: Calculate Indicators ===
def analyze_indicators(df):
    rsi = ta.momentum.RSIIndicator(df['close']).rsi().iloc[-1]
    macd = ta.trend.MACD(df['close'])
    macd_val = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]
    bb = ta.volatility.BollingerBands(df['close'])
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]
    price = df['close'].iloc[-1]
    return {
        'rsi': rsi,
        'macd': macd_val,
        'macd_signal': macd_signal,
        'bb_upper': bb_upper,
        'bb_lower': bb_lower,
        'price': price
    }

# === Logic: Scan Futures Market ===
@app.route('/scan-futures', methods=['POST'])
def scan_futures():
    data = request.get_json()
    budget = data.get("budget", 100)
    leverage_range = data.get("leverage_range", [10, 30])
    confidence_threshold = data.get("confidence_threshold", 90)
    max_trades = data.get("max_trades", 1)
    rrr_min = data.get("rrr_min", 2.5)
    sl_tp_mode = data.get("sl_tp_mode", "atr")
    timeframes = data.get("timeframes", ["15m", "1h"])

    symbols = get_futures_symbols()
    results = []

    for symbol in symbols:
        try:
            df = get_klines(symbol, interval='15m')
            indicators = analyze_indicators(df)

            # התנאים לבחירת טרייד טוב
            rsi = indicators['rsi']
            macd_val = indicators['macd']
            macd_signal = indicators['macd_signal']
            price = indicators['price']

            if rsi < 35 and macd_val > macd_signal:
                direction = "LONG"
            elif rsi > 65 and macd_val < macd_signal:
                direction = "SHORT"
            else:
                continue

            sl = round(price * 0.96, 2) if direction == "LONG" else round(price * 1.04, 2)
            tp = round(price * 1.08, 2) if direction == "LONG" else round(price * 0.92, 2)
            rrr = abs(tp - price) / abs(price - sl)
            confidence = np.random.randint(confidence_threshold, 96)  # סימולציה

            if rrr >= rrr_min:
                results.append({
                    'symbol': symbol,
                    'direction': direction,
                    'entry': round(price, 4),
                    'sl': sl,
                    'tp': tp,
                    'rrr': round(rrr, 2),
                    'confidence': confidence
                })

        except Exception as e:
            print(f"Error with {symbol}: {str(e)}")

    sorted_results = sorted(results, key=lambda x: x['confidence'], reverse=True)
    return jsonify(sorted_results[:max_trades])

# === SL/TP Calculator ===
@app.route('/calculate-sl-tp', methods=['POST'])
def calculate_sl_tp():
    data = request.get_json()
    entry = data.get("entry")
    stop = data.get("stop")
    tp = data.get("tp")
    if not all([entry, stop, tp]):
        return jsonify({'error': 'Missing data'}), 400
    rrr = abs(tp - entry) / abs(entry - stop)
    return jsonify({
        'entry': entry,
        'sl': stop,
        'tp': tp,
        'rrr': round(rrr, 2)
    })

# === Save Trade Example ===
trades = []

@app.route('/save', methods=['POST'])
def save_trade():
    data = request.get_json()
    trades.append(data)
    return jsonify({"message": "Trade saved", "total": len(trades)})

@app.route('/trades', methods=['GET'])
def get_trades():
    return jsonify(trades)

@app.route('/clear', methods=['POST'])
def clear_trades():
    trades.clear()
    return jsonify({"message": "All trades cleared."})

# === Start Server ===
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)




















































