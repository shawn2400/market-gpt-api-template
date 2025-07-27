from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import base64
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from prophet import Prophet
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator
from ta.trend import ADXIndicator
from datetime import datetime
from report_utils import generate_daily_report
from snapshot_utils import save_trade_snapshot
from trade_executor import execute_trade
from binance.client import Client
import requests
import pytz
from backtest_utils import backtest_strategy
import io

app = Flask(__name__)
CORS(app)

# Binance Client Init
binance_api_key = os.getenv("BINANCE_API_KEY")
binance_api_secret = os.getenv("BINANCE_API_SECRET")
client = Client(binance_api_key, binance_api_secret)

# In-memory trade store
trades = []

# --- Utility Functions ---
def scan_all_futures():
    symbols = [
        s["symbol"] for s in client.futures_exchange_info()["symbols"]
        if "USDT" in s["symbol"] and s["contractType"] == "PERPETUAL"
    ]

    results = []
    for symbol in symbols:
        try:
            klines = client.futures_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE, limit=100)
            df = pd.DataFrame(klines, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "number_of_trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            df["volume"] = df["volume"].astype(float)

            if len(df) < 50:
                continue

            rsi = RSIIndicator(df["close"]).rsi().iloc[-1]
            macd = MACD(df["close"]).macd_diff().iloc[-1]
            ema21 = EMAIndicator(df["close"], window=21).ema_indicator().iloc[-1]
            adx = ADXIndicator(df["high"], df["low"], df["close"]).adx().iloc[-1]

            price = df["close"].iloc[-1]
            volume = df["volume"].iloc[-1]

            if (
                rsi < 35 and
                macd > 0 and
                price > ema21 and
                adx > 17 and
                volume > 100000
            ):
                results.append({
                    "symbol": symbol,
                    "last_price": price,
                    "volume": volume,
                    "rsi": round(rsi, 2),
                    "adx": round(adx, 2),
                    "direction": "LONG"
                })

        except Exception:
            continue

    return sorted(results, key=lambda x: x["volume"], reverse=True)

# --- Routes ---
@app.route("/", methods=["GET", "HEAD"])
def index():
    return jsonify({"message": "AlgoGPT API is running"}), 200

@app.route("/backtest", methods=["POST"])
def run_backtest():
    try:
        data = request.json
        df = pd.DataFrame(data["prices"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

        result_df = backtest_strategy(df)
        result_df.dropna(inplace=True)
        result_df["position"] = result_df["signal"].apply(lambda x: 1 if x == "LONG" else (-1 if x == "SHORT" else 0))
        result_df["return"] = result_df["close"].pct_change().fillna(0)
        result_df["strategy_return"] = result_df["position"].shift(1).fillna(0) * result_df["return"]

        total_return = (1 + result_df["strategy_return"]).prod() - 1
        win_rate = (result_df["strategy_return"] > 0).sum() / len(result_df)

        result_df["cumulative"] = (1 + result_df["strategy_return"]).cumprod()
        plt.figure(figsize=(10, 5))
        plt.plot(result_df["timestamp"], result_df["cumulative"], label="Strategy")
        plt.title("Backtest Performance")
        plt.xlabel("Date")
        plt.ylabel("Cumulative Return")
        plt.legend()
        plt.grid(True)
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        chart_base64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()
        plt.close()

        return jsonify({
            "result": result_df.tail(20).to_dict(orient="records"),
            "total_return": round(total_return * 100, 2),
            "win_rate": round(win_rate * 100, 2),
            "chart": chart_base64
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/scan", methods=["GET"])
def scan_market():
    try:
        results = scan_all_futures()
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/execute-trade", methods=["POST"])
def route_execute_trade():
    try:
        trade_data = request.get_json()
        response = execute_trade(trade_data)
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/strategy", methods=["GET"])
def strategy():
    with open("preset.txt", encoding="utf-8") as f:
        return f.read(), 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route("/preset", methods=["GET"])
def preset():
    with open("preset.txt", encoding="utf-8") as f:
        return jsonify({"preset": f.read()})

@app.route("/daily-report", methods=["GET"])
def daily_report():
    try:
        report_path = generate_daily_report()
        with open(report_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return jsonify({"pdf_base64": encoded})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def news():
    try:
        key = os.getenv("CRYPTO_PANIC_API_KEY")
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={key}&kind=news"
        res = requests.get(url)
        return jsonify(res.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/save", methods=["POST"])
def save_trade():
    try:
        data = request.json
        trades.append(data)
        return jsonify({"status": "saved", "total_trades": len(trades)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/trades", methods=["GET"])
def get_trades():
    return jsonify(trades)

@app.route("/clear", methods=["POST"])
def clear_trades():
    trades.clear()
    return jsonify({"status": "cleared"})

@app.route("/open-trades", methods=["GET"])
def open_trades():
    return jsonify([t for t in trades if not t.get("closed")])

@app.route("/close-trade", methods=["POST"])
def close_trade():
    symbol = request.json.get("symbol")
    for t in trades:
        if t["symbol"] == symbol and not t.get("closed"):
            t["closed"] = True
            return jsonify({"status": "closed", "symbol": symbol})
    return jsonify({"error": "Trade not found or already closed"}), 404

@app.route("/sl_tp", methods=["POST"])
def sl_tp():
    try:
        data = request.get_json()
        entry = data["entry"]
        atr = data.get("atr", 0)
        direction = data.get("direction", "LONG")
        rrr = data.get("rrr", 2.5)

        if direction == "LONG":
            stop = entry - atr * 1.5
            tp = entry + rrr * (entry - stop)
        else:
            stop = entry + atr * 1.5
            tp = entry - rrr * (stop - entry)

        return jsonify({"entry": entry, "stop": round(stop, 4), "tp": round(tp, 4), "rrr": rrr})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    try:
        data = request.get_json()
        budget = data["budget"]
        entry = data["entry"]
        leverage = data.get("leverage", 10)
        quantity = round((budget * leverage) / entry, 4)
        return jsonify({"quantity": quantity})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)















































































































