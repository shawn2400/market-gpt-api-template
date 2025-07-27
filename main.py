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
        response = execute_trade(**trade_data)
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# שאר המסלולים לא שונו

















































































































