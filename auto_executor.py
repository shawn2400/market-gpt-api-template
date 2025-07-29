import os
import logging
from utils.binance_client import client
from utils.get_live_price import get_live_price
from utils.quality_score import compute_quality_score
from utils.quantity_utils import auto_risk_allocation
from utils.calculate_quantity import get_step_size
from snapshot_utils import save_trade_snapshot
from utils.pnl_tracker import update_pnl

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

def execute_trade_live(symbol: str, direction: str, entry_price: float, stop_price: float, tp_price: float,
                       leverage: int = 5, budget: float = 100, use_auto_sl_tp: bool = True):
    """
    מבצע טרייד בפועל ב־Binance Futures כולל SL/TP ו־trailing stop.
    """
    try:
        # שליפת מחיר עדכני אם צריך
        if not entry_price:
            entry_price = get_live_price(symbol)

        # חישוב תקציב וכמות לפי סיכון (risk % מתוך budget)
        risk_allocation = auto_risk_allocation(entry_price, stop_price, total_budget=budget, risk_percent=2)
        step = get_step_size(symbol)
        raw_qty = (risk_allocation * leverage) / entry_price
        qty = (int(raw_qty / step)) * step
        qty = round(qty, 6)

        if qty <= 0:
            raise ValueError("כמות לא חוקית (אולי התקציב קטן מדי או stepSize שגוי)")

        # פקודת שוק ראשית
        order = client.futures_create_order(
            symbol=symbol,
            side="BUY" if direction == "LONG" else "SELL",
            type="MARKET",
            quantity=qty
        )
        logging.info(f"✅ פקודת שוק בוצעה: {symbol} {direction} @ {entry_price} | Qty: {qty}")

        # חישוב SL/TP מחדש אם לא נשלחו (option: auto)
        if use_auto_sl_tp:
            if direction == "LONG":
                stop_price = round(entry_price * 0.985, 4)  # SL 1.5% מתחת
                tp_price = round(entry_price * 1.02, 4)     # TP 2% מעל
            else:
                stop_price = round(entry_price * 1.015, 4)
                tp_price = round(entry_price * 0.98, 4)

        # הגדרת SL
        sl_order = client.futures_create_order(
            symbol=symbol,
            side="SELL" if direction == "LONG" else "BUY",
            type="STOP_MARKET",
            stopPrice=stop_price,
            quantity=qty,
            timeInForce="GTC"
        )
        # הגדרת TP
        tp_order = client.futures_create_order(
            symbol=symbol,
            side="SELL" if direction == "LONG" else "BUY",
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price,
            quantity=qty,
            timeInForce="GTC"
        )

        logging.info(f"📍 SL/TP נשלחו עבור {symbol} | SL: {stop_price} | TP: {tp_price}")

        # שמירת snapshot גרפי
        snapshot_path = save_trade_snapshot(symbol, direction, entry_price, stop_price, tp_price)

        # עדכון ל־PNL Tracker
        update_pnl(symbol, direction, entry_price, tp_price, leverage, qty)

        return {
            "symbol": symbol,
            "direction": direction,
            "entry": entry_price,
            "stop": stop_price,
            "tp": tp_price,
            "quantity": qty,
            "leverage": leverage,
            "budget_used": risk_allocation,
            "snapshot": snapshot_path,
            "status": "success"
        }

    except Exception as e:
        logging.error(f"[!] שגיאה בביצוע טרייד: {e}")
        return {"error": str(e), "status": "failed"}
















