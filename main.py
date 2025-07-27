from flask import Flask, request, jsonify
from flask_cors import CORS
from snapshot_utils import save_trade_snapshot
from report_utils import generate_daily_report
from news_utils import get_crypto_news
import os
import json
import base64

app = Flask(__name__)
CORS(app)

# ✅ תיקון: מסלול בריאות (GET /)
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"message": "AlgoGPT API is running"}), 200

@app.route("/preset", methods=["GET"])
def get_preset():
    try:
        with open("preset.txt", "r", encoding="utf-8") as f:
            preset = f.read()
        return jsonify({"preset": preset})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/strategy", methods=["GET"])
def get_strategy_rules():
    try:
        with open("preset.txt", "r", encoding="utf-8") as f:
            strategy = f.read()
        return jsonify({"strategy": strategy})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def crypto_news():
    try:
        news = get_crypto_news()
        return jsonify({"news": news})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/daily-report", methods=["GET"])
def generate_report():
    try:
        pdf_path = generate_daily_report()
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        return jsonify({"pdf_base64": pdf_base64})
    except FileNotFoundError:
        return jsonify({"error": "Statistics file not found"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ai-analyze", methods=["POST"])
def ai_analyze():
    data = request.json
    if not data or "symbol" not in data or "prices" not in data:
        return jsonify({"error": "Missing symbol or prices"}), 400
    try:
        # כאן ייכנס ניתוח prophet או AI עתידי
        return jsonify({
            "symbol": data["symbol"],
            "direction": "LONG",
            "forecast": data["prices"][-5:],
            "chart": ""
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/calculate-quantity", methods=["POST"])
def calculate_quantity():
    data = request.json
    try:
        budget = float(data["budget"])
        entry = float(data["entry"])
        leverage = float(data["leverage"])
        quantity = (budget * leverage) / entry
        return jsonify({"quantity": round(quantity, 4)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ✅ הפעלת השרת
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

















































