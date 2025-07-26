# חלק עליון (imports)
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

# 🆕 החדשים:
from news_utils import fetch_crypto_news, analyze_news_impact
from report_utils import generate_daily_pdf_report

BINANCE_API_KEY = "jJnAfHZd0EWQpX0CA0QNxRnrtsrnW10GQMg6Dx8d9O63mZSzZV7ixSBLNEqTeMIh"
BINANCE_API_SECRET = "soQYlzu6jYiQj8ZLxlXNPWHWTLPRb0EXLK239iFVz1XmnX9EvtDaG7D9zGabCVEq"

app = Flask(__name__)
CORS(app)

trades = []
history = []

# מסלולים קיימים כמו /
# ... (לא מצרף שוב כאן את כל הקוד שלך – אתה כבר יודע שהוא תקין)

# ✅ הוספה: חדשות קריפטו
@app.route("/news", methods=["GET"])
def get_crypto_news():
    raw_news = fetch_crypto_news()
    scored = analyze_news_impact(raw_news)
    return jsonify({"news": scored})

# ✅ הוספה: הפקת דוח יומי PDF
@app.route("/daily-report", methods=["GET"])
def daily_report():
    try:
        with open("pnl_tracker.json", "r") as f:
            pnl_data = json.load(f)
    except:
        return jsonify({"error": "Missing pnl_tracker.json"}), 400

    try:
        pdf_bytes = generate_daily_pdf_report(pnl_data)
        encoded_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
        return jsonify({"pdf_base64": encoded_pdf})
    except Exception as e:
        return jsonify({"error": f"Failed to generate report: {str(e)}"}), 500

# הפעלת Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))






































