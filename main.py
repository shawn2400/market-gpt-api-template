from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import ta
import matplotlib.pyplot as plt
import os
import io
import base64
import hmac
import hashlib
import time
import requests
import json
from datetime import datetime
import pytz
from prophet import Prophet
from news_utils import fetch_crypto_news, analyze_news_impact
from report_utils import generate_daily_pdf_report

# ✅ Binance API Keys (LIVE)
BINANCE_API_KEY = "jJnAfHZd0EWQpX0CA0QNxRnrtsrnW10GQMg6Dx8d9O63mZSzZV7ixSBLNEqTeMIh"
BINANCE_API_SECRET = "soQYlzu6jYiQj8ZLxlXNPWHWTLPRb0EXLK239iFVz1XmnX9EvtDaG7D9zGabCVEq"

# ✅ Flask Setup
app = Flask(__name__)
CORS(app)

trades = []
history = []

# 📈 ברירת מחדל: דשבורד ROOT
@app.route("/")
def home():
    return jsonify({"message": "AlgoGPT API is running"}), 200

# ✅ חדשות קריפטו /news
@app.route("/news", methods=["GET"])
def get_crypto_news():
    try:
        raw_news = fetch_crypto_news()
        scored = analyze_news_impact(raw_news)
        return jsonify({"news": scored})
    except Exception as e:
        return jsonify({"error": f"Failed to fetch news: {str(e)}"}), 500

# ✅ הפקת דוח יומי /daily-report
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

# ✅ ניתוח AI לחיזוי טווחי מחיר עתידיים
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

        # גרף
        fig = model.plot(forecast)
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")

        return jsonify({
            "symbol": symbol,
            "direction": direction,
            "forecast": forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(6).to_dict(orient='records'),
            "chart": image_base64
        })

    except Exception as e:
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500

# 🚀 הפעלת Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))








































