# trade_executor.py

import time
import logging
from math import floor
from binance.enums import *
from utils.binance_client import client
from snapshot_utils import save_trade_snapshot
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.pnl_tracker import log_pnl
from report_utils import send_email_alert
from news_utils import fetch_crypto_news, analyze_news_impact

def round_quantity(symbol, quantity):
    try:
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                step_size = float([f for f in s["filters"] if f["filterType"] == "LOT_SIZE"][0]["stepSize"])
                return floor(quantity / step_size) * step_size
    except Exception as e:
        logging.error(f"[!] שגיאה בעיגול כמות: {e}")
    return round(quantity, 3)

def execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=100, use_grid=False, use_trailing=False, user_id=None):
    try:
        # ניתוח סנטימנט
        news = fetch_crypto_news()
        sentiment = analyze_news_impact(news)
        news_score = sum(n['impact_score'] for n in sentiment if symbol[:3].lower() in n['title'].lower())

        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        price = float(client.futures_symbol_ticker(symbol=symbol)["price"])

        quantity = (budget_usd * leverage) / price
        quantity = round_quantity(symbol, quantity)

        if quantity <= 0:
            raise ValueError("כמות לא חוקית (אולי תקציב נמוך מדי?)")

        side = SIDE_BUY if direction.upper() == "LONG" else SIDE_SELL
        opposite_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY

        client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )

        time.sleep(0.5)

        if use_trailing:
            client.futures_create_order(
                symbol=symbol,
                side=opposite_side,
                type=ORDER_TYPE_TRAILING_STOP_MARKET,
                callbackRate=2.0,
                activationPrice=round(entry, 4),
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )
        else:
            client.futures_create_order(
                symbol=symbol,
                side=opposite_side,
                type=ORDER_TYPE_STOP_MARKET,
                stopPrice=round(stop, 4),
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )

        time.sleep(0.5)

        try:
            client.futures_create_order(
                symbol=symbol,
                side=opposite_side,
                type=ORDER_TYPE_LIMIT,
                price=round(tp, 4),
                quantity=quantity,
                timeInForce=TIME_IN_FORCE_GTC
            )
        except Exception as e:
            logging.warning(f"[!] טייק פרופיט נכשל: {e} — ממשיכים בלעדיו")

        snapshot_path = save_trade_snapshot({
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "direction": direction.upper()
        })

        quality = compute_quality_score({
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "price": price,
            "leverage": leverage
        })

        confidence = round(70 + 3 * quality + news_score * 2, 2)

        trade_data = {
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "direction": direction.upper(),
            "leverage": leverage,
            "confidence": confidence,
            "quality_score": quality,
            "type": "GRID" if use_grid else "REGULAR",
            "user_id": user_id or "default",
            "news_score": news_score
        }

        save_trade(trade_data)
        log_pnl({"symbol": symbol, "entry": entry, "pnl": 0, "success": None})

        send_email_alert(
            subject=f"🔔 AlgoGPT Trade Executed: {symbol} {direction.upper()}",
            body=f"Symbol: {symbol}\nDirection: {direction}\nEntry: {entry}\nStop: {stop}\nTP: {tp}\nLeverage: {leverage}\nConfidence: {confidence:.2f}%\nQuality: {quality}/10\nNews Score: {news_score}"
        )

        return {
            "status": "success",
            "symbol": symbol,
            "entry_price": price,
            "quantity": quantity,
            "stop": stop,
            "tp": tp,
            "leverage": leverage,
            "side": side,
            "confidence": confidence,
            "quality_score": quality,
            "snapshot": snapshot_path,
            "news_score": news_score
        }

    except Exception as e:
        logging.error(f"❌ שגיאה בביצוע טרייד ב־{symbol}: {e}")
        return {"status": "error", "message": str(e)}


















