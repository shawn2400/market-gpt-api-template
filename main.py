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
from utils.pnl_tracker import update_pnl, generate_pnl_pdf  # ✅ חדש

# טעינת משתני סביבה
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
        budget = float(data.get("budget", 100))
        use_grid = bool(data.get("use_grid", False))

        logging.info(f"📤 טרייד: {symbol} {direction} | entry={entry}, stop={stop}, tp={tp}, lev={leverage}, $={budget}, grid={use_grid}")
        result = execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=budget, use_grid=use_grid)
        return jsonify(result)
    except Exception as e:
        logging.error(f"❌ שגיאה בביצוע טרייד: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/scan", methods=["GET"])
def scan():
    try:
        logging.info("🔍 סריקה חיה על Binance Futures...")
        results = scan_all_futures_live()
        logging.info(f"✅ סיום סריקה | נמצאו {len(results)} מועמדים")
        return jsonify(results)
    except Exception as e:
        logging.error(f"❌ שגיאה בסריקה: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
        count = 0

        for trade in top_trades:
            if count >= max_trades:
                break

            symbol = trade['symbol']
            entry = trade['entry']
            stop = trade['stop_loss']
            tp = trade['take_profit']
            direction = trade['signal']
            price = trade['price']
            quality = trade.get("quality_score", 0)

            logging.info(f"🚀 טרייד {count+1}: {symbol} {direction} entry={entry} SL={stop} TP={tp}")

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

            quantity = round((each_budget * leverage) / entry, 4)

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

            exit_price = tp  # הערכה שמגיע ל-TP
            pnl_value = update_pnl(
                symbol=symbol,
                direction=direction,
                entry=entry,
                exit_price=exit_price,
                leverage=leverage,
                qty=quantity
            )

            executed.append({
                "symbol": symbol,
                "entry": entry,
                "stop_loss": stop,
                "take_profit": tp,
                "leverage": leverage,
                "budget_used": each_budget,
                "quantity": quantity,
                "quality_score": quality,
                "pnl_simulated": pnl_value,
                "trade_result": result
            })

            count += 1
            time.sleep(0.5)

        return jsonify({
            "status": "executed",
            "executed_trades": executed
        })

    except Exception as e:
        logging.error(f"❌ שגיאה ב־scan-and-execute (multi): {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/pnl-report", methods=["GET"])
def pnl_report():
    try:
        path = generate_pnl_pdf()
        if not path:
            return jsonify({"status": "no_data", "message": "אין נתוני PNL להיום"}), 404

        with open(path, "rb") as f:
            encoded = f.read()

        return jsonify({
            "status": "ok",
            "report_name": path,
            "pdf_base64": encoded.hex()
        })

    except Exception as e:
        logging.error(f"❌ שגיאה ביצירת דוח PNL: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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

@app.route("/news", methods=["GET"])
def news():
    try:
        news_items = fetch_crypto_news()
        return jsonify(news_items)
    except Exception as e:
        logging.error(f"❌ שגיאה בשליפת חדשות: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/news-impact", methods=["GET"])
def news_impact():
    try:
        news_items = fetch_crypto_news()
        scored = analyze_news_impact(news_items)
        return jsonify(scored)
    except Exception as e:
        logging.error(f"❌ שגיאה בניתוח סנטימנט: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/save-trade", methods=["POST"])
def save_trade_api():
    try:
        data = request.get_json()
        save_trade(data)
        return jsonify({"status": "success", "message": "Trade saved."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/get-trades", methods=["GET"])
def get_trades():
    try:
        trades = load_trades()
        return jsonify({"status": "success", "trades": trades})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/delete-trade", methods=["POST"])
def delete_trade_api():
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        delete_trade(symbol)
        return jsonify({"status": "success", "message": f"Trade {symbol} deleted."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

































































































































