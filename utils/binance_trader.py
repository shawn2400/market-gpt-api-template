# utils/binance_trader.py

from utils.binance_client import client
import time

async def place_futures_order(symbol, side, quantity, entry_price, stop_loss, take_profit, leverage):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity
        )

        time.sleep(0.5)

        # SL
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="STOP_MARKET",
            stopPrice=stop_loss,
            quantity=quantity,
            timeInForce="GTC"
        )

        # TP
        client.futures_create_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="TAKE_PROFIT_MARKET",
            stopPrice=take_profit,
            quantity=quantity,
            timeInForce="GTC"
        )

        return {
            "status": "success",
            "timestamp": int(time.time()),
            "pnl": 0  # אם אין מעקב PNL חי, פשוט תחזיר 0
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
