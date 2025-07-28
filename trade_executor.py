import time
import logging
from math import floor
from binance.enums import *
from utils.binance_client import client
from snapshot_utils import save_trade_snapshot
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.pnl_tracker import update_pnl
from report_utils import send_email_alert
from news_utils import fetch_crypto_news, analyze_news_impact
import pandas as pd

# קאש ל־exchange info לצמצום קריאות מיותרות
EXCHANGE_INFO_CACHE = client.futures_exchange_info()

def round_quantity(symbol, quantity):
    try:
        for s in EXCHANGE_INFO_CACHE["symbols"]:
            if s["symbol"] == symbol:
                step_size = float([f for f in s["filters"] if f["filterType"] == "LOT_SIZE"][0]["stepSize"])
                return floor(quantity / step_size) * step_size
    except Exception as e:
        logging.error(f"[!] שגיאה בעיגול כמות: {e}")
    return round(quantity, 3)

def execute_trade_live(symbol, entry, stop, tp, direction, leverage, budget_usd=100, use_grid=False, use_trailing=False, user_id=None):
    try:
        news = fetch_crypto_news()
        sentiment = analyze_news_impact(news)
        news_score = sum(n['impact_score'] for n in sentiment if symbol[:3].lower() in n['title'].lower())

        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        price = float(client.futures_symbol_ticker(symbol=symbol)["price"])

        quantity = (budget_usd * leverage) / price
        quantity = round_quantity(symbol, quantity)

        if quantity <= 0:
            raise ValueError("⚠️ כמות לא חוקית (תקציב נמוך מדי או tickSize לא מתאים)")

        side = SIDE_BUY if direction.upper() == "LONG" else SIDE_SELL
        opposite_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY

        # שליחת פקודת מרקט
        client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )
        time.sleep(0.5)

        # SL
        if use_trailing:
            activation_price = round(price * 1.005, 4)
            client.futures_create_order(
                symbol=symbol,
                side=opposite_side,
                type=ORDER_TYPE_TRAILING_STOP_MARKET,
                callbackRate=2.0,
                activationPrice=activation_price,
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

        # TP
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
            logging.warning(f"[!] טייק פרופיט נכשל: {e} – ממשיכים בלי")

        # שמירת Snapshot
        snapshot_path = save_trade_snapshot({
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "direction": direction.upper()
        })

        # איכות ו־Confidence
        df = pd.DataFrame([{
            "atr": abs(tp - stop),
            "macd": 1,
            "macd_signal": 0,
            "rsi": 50,
            "adx": 25,
            "volume": 1_000_000,
            "volume_mean": 800_000,
            "close": price,
            "ema_21": price * 0.99,
            "ema_50": price * 0.98
        }])
        quality = compute_quality_score(df)
        confidence = round(70 + 3 * quality + news_score * 2, 2)

        # שמירת טרייד
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
        update_pnl(symbol, direction, entry, price, leverage, quantity)

        send_email_alert(
            subject=f"🔔 AlgoGPT Trade Executed: {symbol} {direction.upper()}",
            body=f"""Symbol: {symbol}
Direction: {direction}
Entry: {entry}
Stop: {stop}
TP: {tp}
Leverage: {leverage}
Confidence: {confidence:.2f}%
Quality: {quality}/10
News Score: {news_score}"""
        )

        return {
            "status": "success",
            "symbol": symbol,
            "entry": entry,
            "price_now": price,
            "quantity": quantity,
            "stop": stop,
            "tp": tp,
            "leverage": leverage,
            "side": side,
            "confidence": confidence,
            "quality_score": quality,
            "news_score": news_score,
            "snapshot": snapshot_path,
            "trailing": use_trailing,
            "grid": use_grid
        }

    except Exception as e:
        logging.error(f"❌ שגיאה בביצוע טרייד ב־{symbol}: {e}")
        return {"status": "error", "message": str(e)}




















