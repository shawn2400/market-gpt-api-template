from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import base64
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from prophet import Prophet
from datetime import datetime, timedelta
import pytz
from ta import trend, momentum, volatility, volume
from news_utils import fetch_crypto_news, analyze_news_impact
from report_utils import generate_daily_pdf_report
from snapshot_utils import save_trade_snapshot
from news_utils import send_email_alert
import threading
import schedule
import time

# ✅ Binance API Keys (LIVE)
BINANCE_API_KEY = "jJnAfHZd0EWQpX0CA0QNxRnrtsrnW10GQMg6Dx8d9O63mZSzZV7ixSBLNEqTeMIh"
BINANCE_API_SECRET = "soQYlzu6jYiQj8ZLxlXNPWHWTLPRb0EXLK239iFVz1XmnX9EvtDaG7D9zGabCVEq"

app = Flask(__name__)
CORS(app)

# Load preset content
with open("preset.txt", "r", encoding="utf-8") as f:
    PRESET_TEXT = f.read()

@app.route("/")
def home():
    return jsonify({"message": "AlgoGPT API is running"}), 200

@app.route("/preset", methods=["GET"])
def get_preset():
    return jsonify({"preset": PRESET_TEXT})

@app.route("/strategy", methods=["GET"])
def get_strategy_rules():
    return jsonify({"strategy": PRESET_TEXT}), 200

@app.route("/news", methods=["GET"])
def get_crypto_news():
    try:
        raw_news = fetch_crypto_news()
        scored = analyze_news_impact(raw_news)
        return jsonify({"news": scored})
    except Exception as e:
        return jsonify({"error": f"Failed to fetch news: {str(e)}"}), 500

@app.route("/daily-report", methods=["GET"])
def daily_report():
    try:
        with open("pnl_tracker.json", "r") as f:
            pnl_data = json.load(f)
    except FileNotFoundError:
        return jsonify({"error": "Missing pnl_tracker.json"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to read pnl data: {str(e)}"}), 500

    try:
        pdf_bytes = generate_daily_pdf_report(pnl_data)
        encoded_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
        return jsonify({"pdf_base64": encoded_pdf})
    except Exception as e:
        return jsonify({"error": f"Failed to generate report: {str(e)}"}), 500

@app.route("/ai-analyze", methods=["POST"])
def ai_analyze():
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        prices = data.get("prices")

        if not symbol or not prices or len(prices) < 20:
            return jsonify({"error": "Missing or invalid input data"}), 400

        df = pd.DataFrame(prices)
        df['ds'] = pd.to_datetime(df['time'])
        df['y'] = df['close']

        model = Prophet(interval_width=0.9)
        model.fit(df[['ds', 'y']])

        future = model.make_future_dataframe(periods=6, freq='H')
        forecast = model.predict(future)

        trend = forecast['trend'].iloc[-1] - forecast['trend'].iloc[-7]
        direction = "LONG" if trend > 0 else "SHORT"

        fig = model.plot(forecast)
        buf = BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")

        # ✅ שמירת Snapshot + Email Alert אוטומטית
        save_trade_snapshot(symbol, direction, forecast, image_base64)
        send_email_alert(symbol, direction, forecast)

        return jsonify({
            "symbol": symbol,
            "direction": direction,
            "forecast": forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(6).to_dict(orient='records'),
            "chart": image_base64
        })

    except Exception as e:
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500

@app.route("/get-trades", methods=["GET"])
def get_trades():
    try:
        with open("pnl_tracker.json", "r") as f:
            trades = json.load(f)
        return jsonify({"trades": trades})
    except FileNotFoundError:
        return jsonify({"trades": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ✅ שליחה יומית אוטומטית של דוח PDF

def run_daily_job():
    try:
        with open("pnl_tracker.json", "r") as f:
            pnl_data = json.load(f)
        pdf_bytes = generate_daily_pdf_report(pnl_data)
        send_email_alert("Daily Report", "Attached daily trading report.", attachment=pdf_bytes)
    except Exception as e:
        print(f"[!] Daily job failed: {e}")

def schedule_jobs():
    schedule.every().day.at("20:30").do(run_daily_job)
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=schedule_jobs, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)











































