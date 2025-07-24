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
import time
import json

app = Flask(__name__)
CORS(app)

trades = []

LOG_PATH = "logs.txt"
TRADES_PATH = "trades.json"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"[{ts}] {msg}\n"
    print(line.strip())
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except:
        pass

def save_trades_file():
    try:
        with open(TRADES_PATH, "w", encoding="utf-8") as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)
        log("🗃️ טריידים נשמרו לקובץ")
    except Exception as e:
        log(f"❌ שגיאה בשמירת טריידים: {e}")

def analyze_coin(df):
    df = df.copy()
    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20).fillna(0)
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50).fillna(0)
    df['RSI'] = ta.momentum.RSIIndicator(df['close']).rsi().fillna(0)
    srsi = ta.momentum.StochRSIIndicator(df['close'])
    df['StochRSI_k'] = srsi.stochrsi_k().fillna(0)
    df['StochRSI_d'] = srsi.stochrsi_d().fillna(0)
    macd = ta.trend.MACD(df['close'])
    df['MACD'] = macd.macd().fillna(0)
    df['MACD_signal'] = macd.macd_signal().fillna(0)
    df['MACD_diff'] = macd.macd_diff().fillna(0)
    adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'])
    df['ADX'] = adx.adx().fillna(0)
    df['DI_plus'] = adx.adx_pos().fillna(0)
    df['DI_minus'] = adx.adx_neg().fillna(0)
    df['OBV'] = ta.volume.OnBalanceVolumeIndicator(df['close'], df['volume']).on_balance_volume().fillna(0)
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14)
    df['ATR'] = atr.average_true_range().fillna(0)

    # Price Action: simple engulfing candle detection
    df['engulf'] = False
    if len(df) >= 2:
        prev = df.iloc[-2]
        cur = df.iloc[-1]
        if cur['open'] < prev['close'] and cur['close'] > prev['open']:
            df.at[df.index[-1], 'engulf'] = True

    return df

def generate_chart(df):
    fig, ax = plt.subplots()
    df['close'].plot(ax=ax, label='Price')
    df['EMA20'].plot(ax=ax, label='EMA20')
    ax.legend(); ax.grid(True)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    log(f"/analyze – קלט התקבל: {data}")
    prices = pd.DataFrame(data['prices'])
    df = analyze_coin(prices)
    last = df.iloc[-1]
    signal = "🔍 ניטרלי"
    if last['engulf']:
        signal = "📣 ENGULFING"
    elif last['close'] > last['EMA50'] and last['MACD'] > last['MACD_signal'] and last['RSI'] < 70 and last['ADX'] > 20:
        signal = "📈 BUY"
    elif last['close'] < last['EMA50'] and last['MACD'] < last['MACD_signal'] and last['RSI'] > 30 and last['ADX'] > 20:
        signal = "📉 SELL"

    chart = generate_chart(df)
    resp = {
        "signal": signal,
        "rsi": round(last['RSI'],2),
        "stochrsi_k": round(last['StochRSI_k'],2),
        "stochrsi_d": round(last['StochRSI_d'],2),
        "macd": round(last['MACD'],5),
        "macd_signal": round(last['MACD_signal'],5),
        "adx": round(last['ADX'],2),
        "di_plus": round(last['DI_plus'],2),
        "di_minus": round(last['DI_minus'],2),
        "obv": round(last['OBV'],2),
        "atr": round(last['ATR'],2),
        "engulf": last['engulf'],
        "image": chart
    }
    log(f"/analyze – תוצאה: {signal}")
    return jsonify(resp)

@app.route("/price", methods=["GET"])
def get_price():
    symbol = request.args.get("symbol", "BTCUSDT").upper()
    log(f"/price – מסמל: {symbol}")
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
        r.raise_for_status()
        price = float(r.json()['price'])
        return jsonify({"symbol": symbol, "price": round(price,6)})
    except Exception as e:
        log(f"/price – שגיאה: {e}")
        return jsonify({"error": str(e)}), 400

@app.route("/calculate-sl-tp", methods=["POST"])
def calculate_sl_tp():
    data = request.get_json()
    log(f"/calculate-sl-tp – קלט: {data}")
    entry = float(data['entry'])
    # dynamic via ATR if provided
    atr = float(data.get("atr",0))
    if atr > 0:
        sl = entry - 1.5*atr
        tp = entry + 3*atr
    else:
        sl = float(data['stop'])
        tp = float(data['target'])
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rrr = round(reward/risk,2) if risk>0 else None
    resp={"rrr": rrr, "risk": round(risk,5), "reward": round(reward,5), "sl": round(sl,5), "tp": round(tp,5)}
    log(f"/calculate-sl-tp – תוצאה: {resp}")
    return jsonify(resp)

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.get_json()
    log(f"/calculate-quantity – קלט: {data}")
    budget = float(data['budget']); leverage=float(data['leverage']); entry=float(data['entry'])
    quantity = round((budget*leverage)/entry,4)
    log(f"/calculate-quantity – תוצאה: {quantity}")
    return jsonify({"quantity":quantity})

@app.route("/save-trade", methods=["POST"])
def save_trade():
    data = request.get_json()
    log(f"/save-trade – טרייד חדש: {data}")
    trades.append(data)
    save_trades_file()
    return jsonify({"message":"Trade saved"})

@app.route("/get-trades", methods=["GET"])
def get_trades():
    log(f"/get-trades – סה\"כ טריידים: {len(trades)}")
    return jsonify(trades)

@app.route("/clear-trades", methods=["POST"])
def clear_trades():
    trades.clear()
    save_trades_file()
    log("clear-trades – נמחקו כל הטריידים")
    return jsonify({"message":"All cleared"})

@app.route("/")
def home():
    return "✅ Market GPT API running"

if __name__=="__main__":
    log("🚀 Server started")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))






















