from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os

from trade_executor import execute_trade_live
from snapshot_utils import analyze_snapshot
from scanner_utils import scan_all_futures
from report_utils import generate_daily_report_base64
from backtest_utils import backtest_strategy, fetch_crypto_news, analyze_news_impact
from datetime import datetime

load_dotenv()
app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return jsonify({"status": "AlgoGPT API is running 🚀"})

@app.route("/scan", methods=["GET"])
def scan_market():
    try:
        results = scan_all_futures()
        if not results:
            return jsonify({"message": "No valid trades found."}), 404
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/execute-trade", methods=["POST"])
def execute_trade():
    try:
        data = request.json
        result = execute_trade_live(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/snapshot", methods=["POST"])
def analyze_snapshot_route():
    try:
        data = request.json
        symbol = data.get("symbol", "BTCUSDT")
        interval = data.get("interval", "1h")
        result = analyze_snapshot(symbol, interval)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/backtest", methods=["POST"])
def backtest():
    try:
        df_json = request.json.get("data", [])
        import pandas as pd
        df = pd.DataFrame(df_json)
        results = backtest_strategy(df)
        return jsonify(results.to_dict(orient="records"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def get_news():
    try:
        news = fetch_crypto_news()
        scored = analyze_news_impact(news)
        return jsonify(scored)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/daily-report", methods=["GET"])
def daily_report():
    try:
        report_base64 = generate_daily_report_base64()
        return jsonify({"pdf_base64": report_base64})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)





















































































































