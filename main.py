import os
import time
import logging
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from trade_executor import execute_trade_live
from scanner_utils import scan_all_futures_live
from backtest_utils import run_backtest, fetch_crypto_news, analyze_news_impact
from utils.trade_storage import save_trade, load_trades, delete_trade
from utils.pnl_tracker import update_pnl, generate_pnl_pdf
from binance.client import Client

load_dotenv()
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "AlgoGPT API is running ✅"})

@app.route("/scan", methods=["GET"])
def scan():
    try:
        results = scan_all_futures_live()
        return jsonify(results)
    except Exception as e:
        logging.error(f"❌ שגיאה בסריקה: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/test-binance", methods=["GET"])
def test_binance():
    try:
        from utils.binance_client import client
        data = client.futures_klines(symbol="BTCUSDT", interval=Client.KLINE_INTERVAL_15MINUTE, limit=5)
        return jsonify({"status": "ok", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/scan-and-execute", methods=["POST"])
def scan_and_execute():
    try:
        data = request.get_json()
        budget = float(data.get("budget", 100))
        leverage = int(data.get("leverage", 10))
        max_trades = int(data.get("max_trades", 2))

        top_trades = scan_all_futures_live(budget_usd=budget)
        if not top_trades:
            return jsonify({"status": "no_trades", "message": "לא נמצאו טריידים מתאימים 🔍"})

        executed = []
        each_budget = budget / max_trades

        for i, trade in enumerate(top_trades[:max_trades]):
            symbol = trade['symbol']
            entry = trade['entry']
            stop = trade['stop_loss']
            tp = trade['take_profit']
            direction = trade['signal']
            quality = trade.get("quality_score", 0)

            result = execute_trade_live(
                symbol=symbol,
                entry=entry,
                stop=stop,
                tp=tp,
                direction=direction,
                leverage=leverage,
                budget_usd=each_budget,
                use_grid=False
            )

            qty = round((each_budget * leverage) / entry, 4)
            save_trade({
                "symbol": symbol,
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "leverage": leverage,
                "direction": direction,
                "confidence": quality,
                "type": "REGULAR"
            })

            pnl_value = update_pnl(
                symbol=symbol,
                direction=direction,
                entry=entry,
                exit_price=tp,
                leverage=leverage,
                qty=qty
            )

            executed.append({
                "symbol": symbol,
                "entry": entry,
                "stop_loss": stop,
                "take_profit": tp,
                "quantity": qty,
                "leverage": leverage,
                "quality_score": quality,
                "pnl_simulated": pnl_value,
                "trade_result": result
            })

            time.sleep(0.5)

        return jsonify({
            "status": "executed",
            "executed_trades": executed
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/pnl-report", methods=["GET"])
def pnl_report():
    try:
        path = generate_pnl_pdf()
        if not path:
            return jsonify({"status": "no_data", "message": "אין דוח זמין להיום"}), 404
        with open(path, "rb") as f:
            encoded = f.read()
        return jsonify({
            "status": "ok",
            "report_name": path,
            "pdf_base64": encoded.hex()
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/backtest", methods=["POST"])
def backtest():
    try:
        data = request.get_json()
        df = pd.DataFrame(data['prices'])
        result = run_backtest(df)
        return jsonify(result.to_dict(orient="records"))
    except Exception as e:
        logging.error(f"❌ שגיאה בבק-טסט: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/news", methods=["GET"])
def crypto_news():
    try:
        news = fetch_crypto_news()
        scored = analyze_news_impact(news)
        return jsonify(scored)
    except Exception as e:
        logging.error(f"❌ שגיאה בשליפת חדשות: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)









































































































































