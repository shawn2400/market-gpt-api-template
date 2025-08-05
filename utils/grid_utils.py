# utils/grid_utils.py

import logging
import math
from utils.binance_client import client
from utils.ws_fallback import get_price
from utils.calculate_quantity import get_precision_info, round_tick

def round_step(value, step):
    return math.floor(value / step) * step

def get_symbol_step(symbol, futures=False):
    try:
        info = client.futures_exchange_info() if futures else client.get_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                result = {"price_step": 0.01, "qty_step": 0.01, "tick_size": 0.01}
                for f in s['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        result['price_step'] = result['tick_size'] = float(f['tickSize'])
                    elif f['filterType'] == 'LOT_SIZE':
                        result['qty_step'] = float(f['stepSize'])
                return result
    except Exception as e:
        logging.error(f"[get_symbol_step] ❌ {symbol}: {e}")
    return {"price_step": 0.01, "qty_step": 0.01, "tick_size": 0.01}

def create_grid_levels(price, tick_size, grid_count, grid_pct=0.5, direction="BOTH"):
    levels = set()
    for i in range(1, grid_count + 1):
        up = round_tick(price * (1 + grid_pct / 100 * i), tick_size)
        down = round_tick(price * (1 - grid_pct / 100 * i), tick_size)
        if direction in ("BOTH", "SELL"):
            levels.add(up)
        if direction in ("BOTH", "BUY"):
            levels.add(down)
    return sorted(levels)

def find_best_leverage(symbol, price, budget, grid_count, qty_step, leverage_min=10, leverage_max=35):
    for lev in range(leverage_max, leverage_min - 1, -1):
        qty = round_step((budget * lev / price) / grid_count, qty_step)
        if qty >= qty_step:
            return lev, qty
    return leverage_min, qty_step

def place_limit_order_with_sl_tp(symbol, side, price, quantity, futures=True, leverage=1, tp_pct=1, sl_pct=1):
    results = {}
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        if futures:
            order = client.futures_create_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                price=round(price, 4),
                quantity=quantity,
                timeInForce="GTC"
            )
            results['order'] = order

            sl_price = round_tick(price * (1 - sl_pct / 100), 0.01) if side == "BUY" else round_tick(price * (1 + sl_pct / 100), 0.01)
            tp_price = round_tick(price * (1 + tp_pct / 100), 0.01) if side == "BUY" else round_tick(price * (1 - tp_pct / 100), 0.01)

            sl = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="STOP_MARKET",
                stopPrice=sl_price,
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC",
                workingType="MARK_PRICE"
            )
            tp = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp_price,
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC",
                workingType="MARK_PRICE"
            )
            results['sl'] = sl
            results['tp'] = tp
        else:
            # לא בשימוש אצלך, אבל נשמר לפיתוח עתידי
            logging.warning("📦 Grid Spot לא נתמך בשלב זה.")
    except Exception as e:
        logging.error(f"[Grid Order] ❌ {symbol} | {side}@{price}: {e}")
        results['error'] = str(e)
    return results

def execute_grid(symbol, budget=100, grid_count=6, grid_pct=0.5,
                leverage_min=10, leverage_max=35, futures=True,
                direction="BOTH", tp_pct=1, sl_pct=1):
    price = get_price(symbol)
    if not price:
        raise RuntimeError(f"⚠️ לא ניתן לקבל מחיר חי עבור {symbol} (ws_fallback)")

    steps = get_symbol_step(symbol, futures=futures)
    price_step = steps["price_step"]
    qty_step = steps["qty_step"]
    tick_size = steps["tick_size"]

    leverage, quantity = find_best_leverage(
        symbol, price, budget, grid_count, qty_step, leverage_min, leverage_max
    )
    if quantity <= 0:
        raise RuntimeError(f"❌ כמות לא חוקית לגריד ({quantity}) – יתכן שתקציב קטן מדי או stepSize גדול")

    levels = create_grid_levels(price, tick_size, grid_count, grid_pct=grid_pct, direction=direction)

    open_orders = []
    for lvl in levels:
        side = "BUY" if lvl < price else "SELL"
        res = place_limit_order_with_sl_tp(
            symbol, side, lvl, quantity, futures=futures, leverage=leverage,
            tp_pct=tp_pct, sl_pct=sl_pct
        )
        open_orders.append({
            "symbol": symbol,
            "side": side,
            "price": lvl,
            "quantity": quantity,
            "leverage": leverage,
            "result": res
        })

    return {
        "symbol": symbol,
        "price": price,
        "budget": budget,
        "leverage": leverage,
        "quantity": quantity,
        "grid_count": grid_count,
        "grid_pct": grid_pct,
        "orders": open_orders
    }

# דוגמה לבדיקת גריד מקומית
if __name__ == "__main__":
    result = execute_grid(
        symbol="BTCUSDT",
        budget=100,
        grid_count=8,
        grid_pct=0.5,
        leverage_min=10,
        leverage_max=35,
        futures=True,
        direction="BOTH",
        tp_pct=1,
        sl_pct=1
    )
    from pprint import pprint
    pprint(result)






