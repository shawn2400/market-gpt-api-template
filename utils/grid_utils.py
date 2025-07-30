# utils/grid_utils.py

import logging
import math
from utils.binance_client import client
from utils.get_live_price import get_live_price
from utils.calculate_quantity import get_precision_info, round_tick

def round_step(value, step):
    """ מעגל value כלפי מטה ל־stepSize החוקי """
    return math.floor(value / step) * step

def get_symbol_step(symbol, futures=False):
    """
    מחזיר את ה־stepSize החוקי של כמות (quantity) ושל מחיר (price).
    מחזיר dict: {'price_step', 'qty_step', 'tick_size'}
    """
    info = client.futures_exchange_info() if futures else client.get_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            price_step = qty_step = tick_size = 0.01
            for f in s['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    price_step = float(f['tickSize'])
                    tick_size = float(f['tickSize'])
                if f['filterType'] == 'LOT_SIZE':
                    qty_step = float(f['stepSize'])
            return {"price_step": price_step, "qty_step": qty_step, "tick_size": tick_size}
    return {"price_step": 0.01, "qty_step": 0.01, "tick_size": 0.01}

def create_grid_levels(price, tick_size, grid_count, grid_pct=0.5, direction="BOTH"):
    """ יוצר רמות גריד מעוגלות לפי tick_size החוקי """
    levels = []
    for i in range(1, grid_count + 1):
        up = round_tick(price * (1 + grid_pct / 100 * i), tick_size)
        down = round_tick(price * (1 - grid_pct / 100 * i), tick_size)
        if direction in ("BOTH", "SELL"):
            levels.append(up)
        if direction in ("BOTH", "BUY"):
            levels.append(down)
    return sorted(set(levels))

def find_best_leverage(symbol, price, budget, grid_count, qty_step, leverage_min=10, leverage_max=35):
    """
    מחזיר את המינוף הכי גבוה שמביא כמות חוקית לגריד, לא נמוך מהמינימום.
    """
    for lev in range(leverage_max, leverage_min - 1, -1):
        qty = round_step((budget * lev / price) / grid_count, qty_step)
        if qty >= qty_step:
            return lev, qty
    return leverage_min, qty_step

def place_limit_order_with_sl_tp(symbol, side, price, quantity, futures=True, leverage=1, tp_pct=1, sl_pct=1):
    results = {}
    try:
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
            # SL/TP עם עיגול tickSize
            sl_price = round_tick(price * (1 - sl_pct / 100), 0.01) if side == "BUY" else round_tick(price * (1 + sl_pct / 100), 0.01)
            tp_price = round_tick(price * (1 + tp_pct / 100), 0.01) if side == "BUY" else round_tick(price * (1 - tp_pct / 100), 0.01)
            sl = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="STOP_MARKET",
                stopPrice=sl_price,
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC"
            )
            tp = client.futures_create_order(
                symbol=symbol,
                side="SELL" if side == "BUY" else "BUY",
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp_price,
                closePosition=False,
                quantity=quantity,
                timeInForce="GTC"
            )
            results['sl'] = sl
            results['tp'] = tp
        else:
            sl_price = round_tick(price * (1 - sl_pct / 100), 0.01) if side == "BUY" else round_tick(price * (1 + sl_pct / 100), 0.01)
            tp_price = round_tick(price * (1 + tp_pct / 100), 0.01) if side == "BUY" else round_tick(price * (1 - tp_pct / 100), 0.01)
            oco = client.create_oco_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=round(price, 4),
                stopPrice=sl_price,
                stopLimitPrice=sl_price,
                limitPrice=tp_price,
                timeInForce="GTC"
            )
            results['oco'] = oco
    except Exception as e:
        logging.error(f"גריד | {symbol} | {side}@{price}: {e}")
        results['error'] = str(e)
    return results

def execute_grid(symbol, budget=100, grid_count=6, grid_pct=0.5, 
                leverage_min=10, leverage_max=35, futures=True, direction="BOTH", tp_pct=1, sl_pct=1):
    """
    פותח גריד דו־צדדי — עם מינוף אופטימלי לפי stepSize, רמות מעוגלות, TP/SL.
    הכל עם עיגול חוקי!
    """
    price = get_live_price(symbol, is_futures=futures)
    if not price:
        raise RuntimeError("⚠️ לא ניתן לקבל מחיר חי מה־API")
    steps = get_symbol_step(symbol, futures=futures)
    price_step = steps["price_step"]
    qty_step = steps["qty_step"]
    tick_size = steps["tick_size"]
    leverage, quantity = find_best_leverage(
        symbol, price, budget, grid_count, qty_step, leverage_min, leverage_max
    )
    if quantity <= 0:
        raise RuntimeError("כמות לא חוקית לגריד (יתכן שתקציב קטן או stepSize בעייתי)")

    levels = create_grid_levels(price, tick_size, grid_count, grid_pct=grid_pct, direction=direction)
    open_orders = []
    for lvl in levels:
        side = "BUY" if lvl < price else "SELL"
        res = place_limit_order_with_sl_tp(
            symbol, side, lvl, quantity, futures=futures, leverage=leverage,
            tp_pct=tp_pct, sl_pct=sl_pct
        )
        open_orders.append({
            "symbol": symbol, "side": side, "price": lvl, "quantity": quantity,
            "leverage": leverage, "result": res
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

# דוגמה לבדיקה
if __name__ == "__main__":
    grid = execute_grid(
        "BTCUSDT", budget=100, grid_count=8, grid_pct=0.5,
        leverage_min=10, leverage_max=35, futures=True, direction="BOTH", tp_pct=1, sl_pct=1
    )
    print("Grid orders:", grid)




