# main.py
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from trade_executor import execute_trade_live
from scanner_utils import scan_all_futures
from backtest_utils import run_backtest
import pandas as pd
import logging

load_dotenv()

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "AlgoGPT API is running ✅"})

@app.route("/execute-trade", methods=["POST"])
def execute_trade():
    try:
        data = request.get_json()
        symbol = data["symbol"]
        entry = float(data["entry"])
        stop = float(data["stop"])
        tp = float(data["tp"])
        direction = data["direction"]
        leverage = int(data.get("leverage", 10))

        logging.info(f"📤 ביצוע טרייד: {symbol} | {direction} | entry={entry}, stop={stop}, tp={tp}, lev={leverage}")
        result = execute_trade_live(symbol, entry, stop, tp, direction, leverage)
        return jsonify(result)
    except Exception as e:
        logging.error(f"❌ שגיאה בביצוע טרייד: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/scan", methods=["GET"])
def scan():
    try:
        logging.info("🔍 התחלת סריקה חיה על Binance Futures...")
        results = scan_all_futures()
        logging.info(f"✅ הסתיימה סריקה: נמצאו {len(results)} תוצאות")
        return jsonify(results)
    except Exception as e:
        logging.error(f"❌ שגיאה בסריקה: {e}")
        return jsonify({"status": "error", "message": "שגיאה בסריקה", "details": str(e)}), 500

@app.route("/backtest", methods=["POST"])
def backtest():
    try:
        data = request.get_json()
        df = pd.DataFrame(data["data"])
        if 'timestamp' not in df.columns:
            df['timestamp'] = pd.date_range(start='2023-01-01', periods=len(df), freq='15min')
        results = run_backtest(df)
        return jsonify(results.to_dict(orient="records"))
    except Exception as e:
        logging.error(f"❌ שגיאה ב־Backtest: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)



























































































































