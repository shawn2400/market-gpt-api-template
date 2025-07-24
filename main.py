from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import pandas as pd
import ta
import os

app = Flask(__name__)
CORS(app)

BINANCE_BASE_URL = "https://api.binance.com"

def fetch_klines(symbol: str, interval: str = "15m", limit: int = 100):
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        raise ValueError(f"Binance API error: {response.status_code}")
    klines = response.json()
    df = pd.DataFrame(klines, columns=[
        'time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    return df

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    symbol = data.get('symbol')
    if not symbol:
        return jsonify({"error": "Missing symbol"}), 400

    try:
        df_15m = fetch_klines(symbol, "15m", 100)
        df_1h = fetch_klines(symbol, "1h", 100)
        df_4h = fetch_klines(symbol, "4h", 100)

        def extract_indicators(df):
            df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
            df['ema20'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
            df['ema50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
            df['macd'] = ta.trend.MACD(df['close']).macd_diff()
            bb = ta.volatility.BollingerBands(df['close'])
            df['bb_upper'] = bb.bollinger_hband()
            df['bb_lower'] = bb.bollinger_lband()
            df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
            
            candle = ""
            last = df.iloc[-2]
            body = abs(float(last['close']) - float(last['open']))
            upper_wick = float(last['high']) - max(float(last['close']), float(last['open']))
            lower_wick = min(float(last['close']), float(last['open'])) - float(last['low'])
            
            if body < upper_wick and body < lower_wick:
                candle = "נר פטיש או דחיפה"
            elif last['close'] > last['open'] and body > upper_wick and body > lower_wick:
                candle = "נר שורי חזק"
            elif last['close'] < last['open'] and body > upper_wick and body > lower_wick:
                candle = "נר דובי חזק"

            return {
                "price": round(df['close'].iloc[-1], 4),
                "rsi": round(df['rsi'].iloc[-1], 2),
                "ema20": round(df['ema20'].iloc[-1], 4),
                "ema50": round(df['ema50'].iloc[-1], 4),
                "macd": round(df['macd'].iloc[-1], 4),
                "bb_upper": round(df['bb_upper'].iloc[-1], 4),
                "bb_lower": round(df['bb_lower'].iloc[-1], 4),
                "atr": round(df['atr'].iloc[-1], 4),
                "candle": candle
            }

        ind_15m = extract_indicators(df_15m)
        ind_1h = extract_indicators(df_1h)
        ind_4h = extract_indicators(df_4h)

        reasons = []
        score = 0

        for label, ind in zip(["15m", "1h", "4h"], [ind_15m, ind_1h, ind_4h]):
            local = []
            if ind['price'] > ind['ema20'] and ind['price'] > ind['ema50']:
                local.append(f"{label}: מחיר מעל EMA20/50")
                score += 1
            if ind['macd'] > 0:
                local.append(f"{label}: MACD חיובי")
                score += 1
            if ind['rsi'] < 30:
                local.append(f"{label}: RSI ב־Oversold")
                score += 1
            elif ind['rsi'] > 70:
                local.append(f"{label}: RSI ב־Overbought")
                score -= 1
            if ind['candle']:
                local.append(f"{label}: {ind['candle']}")
                score += 1
            reasons.extend(local)

        if score >= 6:
            signal = "📈 BUY signal detected"
        elif score <= -3:
            signal = "📉 SELL signal detected"
        else:
            signal = "⏸️ ניטרלי – דרוש אישור נוסף"

        return jsonify({
            "symbol": symbol,
            "recommendation": signal,
            "confidence": f"{round((score/9)*100, 1)}%",
            "score": score,
            "15m": ind_15m,
            "1h": ind_1h,
            "4h": ind_4h,
            "analysis": reasons
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# שאר הנתיבים נשארים כפי שהגדרת קודם – calculate-sl-tp, quantity וכו...

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











