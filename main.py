from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
import pandas as pd
import ta
import matplotlib.pyplot as plt
import io
import base64
import requests
import os

app = Flask(__name__)
CORS(app)

trades = []  # זיכרון זמני לטריידים

# פונקציה לחישוב אינדיקטורים
def analyze_coin(df):
    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20).fillna(0)
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50).fillna(0)
    df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200).fillna(0)
    df['RSI'] = ta.momentum.RSIIndicator(df['close']).rsi().fillna(0)
    macd = ta.trend.MACD(df['close'])
    df['MACD'] = macd.macd().fillna(0)
    df['MACD_signal'] = macd.macd_signal().fillna(0)
    df['MACD_diff'] = macd.macd_diff().fillna(0)
    bb = ta.volatility.BollingerBands(df['close'])
    df['BB_high'] = bb.bollinger_hband().fillna(0)
    df['BB_low'] = bb.bollinger_lband().fillna(0)
    return df

# יצירת גרף כתמונה
def generate_chart(df):
    fig, ax = plt.subplots()
    df['close'].plot(ax=ax, label='Price')
    df['EMA20'].plot(ax=ax, label='EMA20')
    df['EMA50'].plot(ax=ax, label='EMA50')
    ax.grid(True)
    plt.legend()
    plt.title("Technical Chart")
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode('utf-8')
    return image_base64

# ניתוח טכני
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        prices = pd.DataFrame(data['prices'])
        df = analyze_coin(prices)
        last = df.iloc[-1]
        signal = "🔍 ניטרלי"
        if last['close'] > last['EMA50'] and last['MACD'] > last['MACD_signal'] and last['RSI'] < 70:
            signal = "📈 אות קנייה (BUY)"
        elif last['close'] < last['EMA50'] and last['MACD'] < last['MACD_signal'] and last['RSI'] > 30:
            signal = "📉 אות מכירה (SELL)"
        chart = generate_chart(df)
        return jsonify({
            "signal": signal,
            "rsi": round(last['RSI'], 2),
            "macd": round(last['MACD'], 5),
            "ema": round(last['EMA50'], 2),
            "image": chart
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ✅ חישוב SL/TP – מתוקן ומינימליסטי
@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    try:
        data = request.get_json()
        entry = float(data['entry'])
        stop = float(data['stop'])
        target = float(data['target'])
        risk = round(abs(entry - stop), 5)
        reward = round(abs(target - entry), 5)
        rrr = round(reward / risk, 2) if risk != 0 else None
        return jsonify({
            "rrr": rrr,
            "risk": risk,
            "reward": reward
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# חישוב כמות לפי תקציב
@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    try:
        data = request.get_json()
        budget = float(data['budget'])
        leverage = float(data['leverage'])
        entry = float(data['entry'])
        quantity = round((budget * leverage) / entry, 4)
        return jsonify({"quantity": quantity})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# שמירת טרייד בזיכרון
@app.route("/save-trade", methods=["POST"])
def save_trade():
    try:
        trade = request.get_json()
        trades.append(trade)
        return jsonify({"message": "Trade saved successfully!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# שליפת כל הטריידים
@app.route("/get-trades", methods=["GET"])
def get_trades():
    return jsonify(trades)

# ניקוי רשימת הטריידים
@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    trades.clear()
    return jsonify({"message": "All trades cleared."})

# מחיר חי מבינאנס
@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol", "BTCUSDT")
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return jsonify({
            "symbol": symbol.upper(),
            "price": round(float(data['price']), 6)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# בדיקה שה־API רץ
@app.route("/")
def home():
    return "✅ Market GPT API is running."

# הפעלת השרת
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))



















