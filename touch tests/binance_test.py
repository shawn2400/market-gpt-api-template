@app.route("/test-binance", methods=["GET"])
def test_binance():
    try:
        from utils.binance_client import client
        data = client.futures_klines(symbol="BTCUSDT", interval=Client.KLINE_INTERVAL_15MINUTE, limit=5)
        return jsonify({"status": "ok", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

