# ✅ main.py – Flask API for Crypto Trade Analysis
from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
import pandas as pd
import ta
import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__)
CORS(app)

trades = []  # זיכרון זמני לטריידים

# פונקציה לחישוב אינדיקטורים
def analyze_coin(df):
    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20).fillna(0)
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50).fillna(0)
    df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200).fillna(0)
    df['RSI'] = ta.momentum.RSIIndicator(df['close']).rsi().fillna(0)
    df['MACD'] = ta.trend.MACD(df['close']).macd_diff().fillna(0)
    df['BB_high'] = ta.volatility.BollingerBands(df['close']).bollinger_hband().fillna(0)
    df['BB_low'] = ta.volatility.BollingerBands(df['close']).bollinger_lband().fillna(0)
    return df

# יצירת גרף כתמונה

def generate_chart(df):
    fig, ax = plt.subplots()
    df['close'].plot(ax=ax, label='Price')
    df['EMA20'].plot(ax=ax, label='EMA20')
    df['EMA50'].plot(ax=ax, label='EMA50')
    plt.legend()
    plt.title("Technical Chart")
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode('utf-8')
    return image_base64

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    prices = pd.DataFrame(data['prices'])
    df = analyze_coin(prices)
    last = df.iloc[-1]

    signal = "🔍 ניטרלי"
    if last['close'] > last['EMA50'] and last['MACD'] > 0 and last['RSI'] < 70:
        signal = "📈 אות קנייה (BUY)"
    elif last['close'] < last['EMA50'] and last['MACD'] < 0 and last['RSI'] > 30:
        signal = "📉 אות מכירה (SELL)"

    chart = generate_chart(df)
    return jsonify({
        "signal": signal,
        "rsi": round(last['RSI'], 2),
        "macd": round(last['MACD'], 5),
        "ema": round(last['EMA50'], 2),
        "image": chart
    })

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.get_json()
    entry = float(data['entry'])
    stop = float(data['stop'])
    target = float(data['target'])
    risk = round(entry - stop, 5)
    reward = round(target - entry, 5)
    rrr = round(reward / risk, 2) if risk != 0 else None
    return jsonify({"RRR": rrr, "Risk": risk, "Reward": reward})

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.get_json()
    budget = float(data['budget'])
    leverage = float(data['leverage'])
    entry = float(data['entry'])
    quantity = round((budget * leverage) / entry, 4)
    return jsonify({"quantity": quantity})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    trade = request.get_json()
    trades.append(trade)
    return jsonify({"message": "Trade saved successfully!"})

@app.route("/get-trades", methods=["GET"])
def get_trades():
    return jsonify(trades)

@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    trades.clear()
    return jsonify({"message": "All trades cleared."})

@app.route("/")
def home():
    return "✅ Market GPT API is running."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)












