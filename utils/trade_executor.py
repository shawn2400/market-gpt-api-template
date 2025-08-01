import logging
import time
import os
import pandas as pd

from utils.quantity_utils import calculate_quantity, auto_risk_allocation
from utils.ai_analysis import predict_optimal_sl_tp
from utils.ws_fallback import get_price
from utils.trade_storage import save_trade
from utils.quality_score import compute_quality_score
from utils.snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl
from utils.report_utils import send_email_alert
from utils.binance_client import client
from utils.precision_utils import round_to_precision, get_precision_info

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"
ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_STOP_MARKET = "STOP_MARKET"
ORDER_TYPE_TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"
TIME_IN_FORCE_GTC = "GTC"

def execute_trade_live(
    symbol,
    entry,
    stop,
    tp,
    direction,
    leverage,
    budget_usd=100,
    use_grid=False,
    use_trailing=False,
    user_id=None,
    take_snapshot=True,
    market_type="futures"
):
    try:
        # הגדרת מינוף
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # קבלת המחיר העדכני
        price = get_price(symbol, market_type=market_type)
        if not price or price <= 0:
            raise ValueError("⚠️ לא ניתן לשלוף מחיר עדכני")

        # חישוב SL/TP אוטומטי אם לא סופק
        if stop is None or tp is None:
            sltp = predict_optimal_sl_tp(direction, entry)
            stop = sltp["sl"]
            tp = sltp["tp"]

        # עיגול לפי הדיוק של הבורסה
        precision = get_precision_info(symbol)
        stop = round_to_precision(stop, precision.get("pricePrecision", 4))
        tp = round_to_precision(tp, precision.get("pricePrecision", 4))

        # חישוב גודל עמדה לפי שינוי סיכון (USD)
        capital_used = auto_risk_allocation(symbol, budget_usd)
        quantity = calculate_quantity(symbol, entry, leverage, capital_used)
        if quantity <= 0:
            raise ValueError("⚠️ כמות לא חוקית – אולי תקציב קטן מדי או דיוק לא נכון")

        # ביצוע הזמנה שוק
        side = SIDE_BUY if direction.upper() == "LONG" else SIDE_SELL
        opposite = SIDE_SELL if side == SIDE_BUY else SIDE_BUY
        client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )
        time.sleep(0.5)

        # Stop / trailing
        if use_trailing:
            activation_price = round(price * (1.005 if direction.upper() == "LONG" else 0.995), 4)
            client.futures_create_order(
                symbol=symbol,
                side=opposite,
                type=ORDER_TYPE_TRAILING_STOP_MARKET,
                activationPrice=activation_price,
                callbackRate=2.0,
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )
        else:
            client.futures_create_order(
                symbol=symbol,
                side=opposite,
                type=ORDER_TYPE_STOP_MARKET,
                stopPrice=round(stop, 4),
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )

        # Take-profit
        try:
            client.futures_create_order(
                symbol=symbol,
                side=opposite,
                type=ORDER_TYPE_LIMIT,
                price=round(tp, 4),
                quantity=quantity,
                timeInForce=TIME_IN_FORCE_GTC
            )
        except Exception as e:
            logging.warning(f"[!] טייק פרופיט נכשל: {e}")

        # שמירת סנאפשוט
        snapshot_path = None
        if take_snapshot:
            snapshot_path = save_trade_snapshot({
                "symbol": symbol,
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "direction": direction.upper()
            })

        # חישוב איכות ומידת ביטחון
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
        confidence = round(70 + 3 * quality, 2)

        # שמירת סחר במאגר
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
            "capital_used": round(capital_used, 2),
            "quantity": quantity,
            "status": "OPEN",
            "snapshot": snapshot_path,
            "opened_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_trade(trade_data)
        update_pnl(symbol, direction, entry, price, leverage, quantity)

        # שליחת אימייל אם מוגדר
        if os.getenv("ALERT_EMAIL_ADDRESS") and os.getenv("ALERT_TO_EMAIL"):
            try:
                send_email_alert(
                    subject=f"🔔 AlgoGPT Trade Executed: {symbol} {direction.upper()}",
                    message=(
                        f"Symbol: {symbol}\n"
                        f"Direction: {direction}\n"
                        f"Entry: {entry}\n"
                        f"Stop: {stop}\n"
                        f"TP: {tp}\n"
                        f"Leverage: {leverage}\n"
                        f"Confidence: {confidence:.2f}%\n"
                        f"Quality: {quality}/10\n"
                        f"Capital Used: {capital_used:.2f}$\n"
                        f"Qty: {quantity}"
                    )
                )
            except Exception as e:
                logging.warning(f"[!] שליחת אימייל נכשלה: {e}")

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
            "snapshot": snapshot_path,
            "trailing": use_trailing,
            "grid": use_grid,
            "capital_used": capital_used
        }

    except Exception as e:
        logging.error(f"❌ שגיאה בביצוע טרייד ב־{symbol}: {e}")
        return {"status": "error", "message": str(e)}


































