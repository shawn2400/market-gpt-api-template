import time
import logging
from math import floor
import asyncio
import pandas as pd
import json
from binance.enums import *
from utils.binance_client import client
from utils.get_live_price import get_live_price
from snapshot_utils import save_trade_snapshot
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.pnl_tracker import update_pnl
from report_utils import send_email_alert
from news_utils import fetch_crypto_news, analyze_news_impact
from utils.scan_futures import scan_all  # שים לב לשם הפונקציה העדכנית
from utils.ai_analysis import predict_optimal_sl_tp

# קאש למידע הבורסה
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

        price = get_live_price(symbol)
        if not price:
            raise ValueError("⚠️ לא ניתן לשלוף מחיר עדכני")

        if not stop or not tp:
            sl_tp = predict_optimal_sl_tp(symbol, price, direction)
            stop = sl_tp.get("sl")
            tp = sl_tp.get("tp")

        quantity = (budget_usd * leverage) / price
        quantity = round_quantity(symbol, quantity)
        if quantity <= 0:
            raise ValueError("⚠️ כמות לא חוקית")

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
            activation_price = round(price * 1.005 if direction.upper() == "LONG" else price * 0.995, 4)
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
            logging.warning(f"[!] טייק פרופיט נכשל: {e} – ממשיכים בלעדו")

        snapshot_path = save_trade_snapshot({
            "symbol": symbol,
            "entry": entry,
            "stop": stop,
            "tp": tp,
            "direction": direction.upper()
        })

        df = pd.DataFrame([{  # נתונים לדוגמה לציון איכות
            "atr": abs(tp - stop),
            "macd": 1,
            "macd_signal": 0,
            "rsi": 50,
            "adx": 25,
            "volume": 1000000,
            "volume_mean": 800000,
            "close": price,
            "ema_21": price * 0.99,
            "ema_50": price * 0.98
        }])
        quality = compute_quality_score(df)
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
            "mock_quality": True,
            "type": "GRID" if use_grid else "REGULAR",
            "user_id": user_id or "default",
            "news_score": news_score
        }
        save_trade(trade_data)
        update_pnl(symbol, direction, entry, price, leverage, quantity)

        with open("email_config.json", "r") as f:
            cfg = json.load(f)
            to_emails = [cfg.get("to_email", "shaharabecassis8@gmail.com")]

        send_email_alert(
            subject=f"🔔 AlgoGPT Trade Executed: {symbol} {direction.upper()}",
            message=f"""Symbol: {symbol}
Direction: {direction}
Entry: {entry}
Stop: {stop}
TP: {tp}
Leverage: {leverage}
Confidence: {confidence:.2f}%
Quality: {quality}/10
News Score: {news_score}""",
            to_emails=to_emails
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
        logging.error(f"❌ שגיאה בביצוע טרייד ב‏{symbol}: {e}")
        return {"status": "error", "message": str(e)}


async def start_auto_executor(delay=60, min_quality=6, max_budget=100):
    while True:
        try:
            print(f"[AUTO_EXECUTOR] מתחיל סריקה חיה... (min_quality={min_quality})")
            trades = await scan_all(min_quality=min_quality)  # עדכון לשם הפונקציה הנכון

            filtered = [t for t in trades if t.get("quality_score", 0) >= min_quality]
            if not filtered:
                print("[AUTO_EXECUTOR] לא נמצאו טריידים מתאימים")
                await asyncio.sleep(delay)
                continue

            trade = filtered[0]
            print(f"[AUTO_EXECUTOR] מבצע טרייד חי על {trade['symbol']} ({trade['direction']})")

            await asyncio.to_thread(
                execute_trade_live,
                symbol=trade["symbol"],
                entry=trade.get("close", None),
                stop=trade.get("stop", None),
                tp=trade.get("tp", None),
                direction=trade["direction"],
                leverage=10,
                budget_usd=max_budget,
                use_grid=False,
                use_trailing=True
            )

        except Exception as e:
            logging.error(f"[AUTO_EXECUTOR] שגיאה: {e}")

        await asyncio.sleep(delay)














