from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from fpdf import FPDF
from datetime import datetime
import base64
import matplotlib.pyplot as plt
from prophet import Prophet
import pandas as pd
import requests

app = Flask(__name__)
CORS(app)

# 🟢 ברירת מחדל ל־preset
PRESET_PATH = "preset.txt"

@app.route("/")
def health_check():
    return jsonify({"message": "AlgoGPT API is running"})

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    try:
        data = request.get_json()
        budget = data["budget"]
        entry = data["entry"]
        leverage = data["leverage"]
        quantity = round((budget * leverage) / entry, 6)
        return jsonify({"quantity": quantity})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/preset", methods=["GET"])
def get_preset():
    try:
        with open(PRESET_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"preset": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/strategy", methods=["GET"])
def get_strategy_rules():
    try:
        with open(PRESET_PATH, "r", encoding="utf-8") as f:
            strategy = f.read()
        return jsonify({"strategy": strategy})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def get_crypto_news():
    try:
        response = requests.get("https://cryptopanic.com/api/v1/posts/?auth_token=89404de8e0bb4d6e78e95ed26ff19970cdb8830a&public=true")
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch news"}), 500
        news_data = response.json()
        return jsonify({"news": news_data.get("results", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/daily-report", methods=["GET"])
def generate_daily_report():
    try:
        stats_path = "pnl_tracker.json"
        if not os.path.exists(stats_path):
            return jsonify({"error": "No stats file found"}), 400

        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        pdf.cell(200, 10, txt="Daily Performance Report", ln=True, align="C")
        pdf.cell(200, 10, txt=f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=True, align="C")
        pdf.ln(10)

        for key, value in stats.items():
            pdf.cell(200, 10, txt=f"{key}: {value}", ln=True)

        report_path = "daily_report.pdf"
        pdf.output(report_path)

        with open(report_path, "rb") as f:
            encoded_pdf = base64.b64encode(f.read()).decode("utf-8")

        return jsonify({"pdf_base64": encoded_pdf})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ai-analyze", methods=["POST"])
def ai_analyze():
    try:
        data = request.get_json()
        symbol = data["symbol"]
        prices = data["prices"]

        df = pd.DataFrame(prices)
        df["ds"] = pd.to_datetime(df["time"])
        df["y"] = df["close"]
        model = Prophet()
        model.fit(df[["ds", "y"]])
        future = model.make_future_dataframe(periods=5, freq='H')
        forecast = model.predict(future)

        plt.figure(figsize=(10, 5))
        model.plot(forecast)
        plt.title(f"{symbol} Forecast")
        plt.tight_layout()
        chart_path = f"{symbol}_forecast.png"
        plt.savefig(chart_path)

        with open(chart_path, "rb") as f:
            encoded_chart = base64.b64encode(f.read()).decode("utf-8")

        output = {
            "symbol": symbol,
            "direction": "LONG" if forecast["yhat"].iloc[-1] > df["y"].iloc[-1] else "SHORT",
            "forecast": forecast[["ds", "yhat"]].tail(5).to_dict(orient="records"),
            "chart": encoded_chart
        }
        return jsonify(output)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


















































