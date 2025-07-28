from flask import Flask, request, jsonify
from flask_cors import CORS
from trade_executor import execute_trade_live

app = Flask(__name__)
CORS(app)

@app.route('/execute-trade', methods=['POST'])
def execute_trade():
    try:
        data = request.get_json()
        symbol = data["symbol"]
        entry = float(data["entry"])
        stop = float(data["stop"])
        tp = float(data["tp"])
        direction = data["direction"]
        leverage = int(data["leverage"])
        budget = float(data.get("budget", 100))
        use_grid = bool(data.get("use_grid", False))

        result = execute_trade_live(
            symbol=symbol,
            entry=entry,
            stop=stop,
            tp=tp,
            direction=direction,
            leverage=leverage,
            budget_usd=budget,
            use_grid=use_grid
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# בדיקת תקינות
@app.route("/")
def home():
    return "AlgoGPT API Running ✅"















