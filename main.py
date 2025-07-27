import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from trade_executor import execute_trade_live
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

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

        result = execute_trade_live(symbol, entry, stop, tp, direction, leverage)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
























































































































