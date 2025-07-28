import os
import time
import logging
import pandas as pd
import numpy as np
import threading
import aiohttp
from aiohttp import web
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# ייבוא פנימי (כמו בקוד שלך)
from trade_executor import execute_trade_live
from scanner_utils import scan_all_futures_live
from backtest_utils import run_backtest, fetch_crypto_news, analyze_news_impact
from utils.trade_storage import save_trade, load_trades, delete_trade
from utils.pnl_tracker import update_pnl, generate_pnl_pdf

load_dotenv()
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

# ========== Flask Endpoints ==========
@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "AlgoGPT API is running ✅"})

@app.route("/.well-known/ai-plugin.json")
def serve_plugin_manifest():
    return send_from_directory(".well-known", "ai-plugin.json")

@app.route("/scan", methods=["GET"])
def scan():
    try:
        results = scan_all_futures_live()
        return jsonify({"status": "ok", "results": results})
    except Exception as e:
        logging.error(f"❌ שגיאה בסריקה: {e}")
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

def run_flask():
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# ========== AIOHTTP ==========
async def fetch_binance_futures_data():
    url = 'https://fapi.binance.com/fapi/v1/ticker/24hr'
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()

async def scan_futures_market(request):
    try:
        raw_data = await fetch_binance_futures_data()
        top_20 = sorted(raw_data, key=lambda x: float(x['quoteVolume']), reverse=True)[:20]

        results = []
        for item in top_20:
            rsi = np.random.uniform(20, 80)
            adx = np.random.uniform(10, 50)
            direction = "LONG" if rsi < 30 else "SHORT" if rsi > 70 else "NEUTRAL"

            results.append({
                'symbol': item['symbol'],
                'last_price': float(item['lastPrice']),
                'volume': float(item['quoteVolume']),
                'rsi': round(rsi, 2),
                'adx': round(adx, 2),
                'direction': direction
            })

        return web.json_response({'results': results})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

def run_aiohttp():
    aio_app = web.Application()
    aio_app.router.add_get('/scan_futures_market', scan_futures_market)
    port = int(os.environ.get('PORT', 8080))
    web.run_app(aio_app, port=port)

# ========== MAIN ==========
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    threading.Thread(target=run_aiohttp).start()










































































































































