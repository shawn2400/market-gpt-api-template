# scanner_utils.py
import os
import json
import requests
import pandas as pd
import time
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from utils.quality_score import compute_quality_score
from utils.quantity_utils import calculate_quantity
from trade_executor import execute_trade_live  # ✅ הפעלה אוטומטית של טרייד
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
BASE_URL = "https://fapi.binance.com"
HOST_HEADER = {}

# ✅ בדיקה אם יש כבר פוזיציה פתוחה

def is_position_open(symbol):
    try:
        with open("pnl_tracker.json", "r") as f:
            data = json.load(f)
        return any(t["symbol"] == symbol and not t.get("closed") for t in data)
    except Exception:
        return False

# ✅ שמירת לוג של טריידים מוצלחים

def log_trade(trade_data):
    try:
        if not os.path.exists("executed_trades.json"):
            with open("executed_trades.json", "w") as f:
                json.dump([], f)
        with open("executed_trades.json", "r+") as f:
            existing = json.load(f)
            existing.append(trade_data)
            f.seek(0)
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f"[!] שגיאה בלוג טרייד: {e}")

# ✅ שליפת מחירי Futures עם טיפול בשגיאה

def get_futures_prices():
    url = f"{BASE_URL}/fapi/v1/ticker/price"
    headers = {"X-MBX-APIKEY": API_KEY, **HOST_HEADER}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[!] שגיאה בשליפת מחירי Futures: {e}")
        return []

# ✅ שליפת נתוני קנדלים ל־symbol עם טיפול בשגיאה

def get_klines(symbol, interval="15m", limit=50):
    url = f"{BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    headers = {"X-MBX-APIKEY": API_KEY, **HOST_HEADER}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
        return df
    except requests.exceptions.RequestException as e:
        print(f"[!] שגיאה בשליפת קווים ל־{symbol}: {e}")
        return pd.DataFrame()

# ✅ ניתוח טיימפריים כפול

def analyze_dual_timeframes(df_15m, df_1h):
    def get_signal(df):
        rsi = RSIIndicator(df['close']).rsi().iloc[-1]
        macd = MACD(df['close']).macd_diff().iloc[-1]
        ema = EMAIndicator(df['close'], 21).ema_indicator().iloc[-1]
        price = df['close'].iloc[-1]
        adx = ADXIndicator(df['high'], df['low'], df['close']).adx().iloc[-1]

        if rsi < 30 and macd > 0 and price > ema and adx > 17:
            return 'LONG'
        elif rsi > 70 and macd < 0 and price < ema and adx > 17:
            return 'SHORT'
        else:
            return None

    tf15_signal = get_signal(df_15m)
    tf1h_signal = get_signal(df_1h)
    return tf15_signal if tf15_signal == tf1h_signal else None

# ✅ סריקה חכמה עם ביצוע אוטומטי לטרייד החזק ביותר

def scan_all_futures(budget_per_trade=100, leverage=10):
    prices = get_futures_prices()
    results = []
    executed_trade = None

    for item in prices:
        symbol = item["symbol"]
        if not symbol.endswith("USDT") or any(x in symbol for x in ["DOWN", "UP", "BULL", "BEAR"]):
            continue
        if is_position_open(symbol):
            continue

        try:
            df_15m = get_klines(symbol, interval="15m", limit=50)
            df_1h = get_klines(symbol, interval="1h", limit=50)

            if df_15m.empty or df_1h.empty:
                continue

            signal = analyze_dual_timeframes(df_15m, df_1h)
            if not signal:
                continue

            df_15m["ema_21"] = EMAIndicator(df_15m["close"], window=21).ema_indicator()
            df_15m["macd"] = MACD(df_15m["close"]).macd_diff()
            df_15m["rsi"] = RSIIndicator(df_15m["close"]).rsi()
            df_15m["adx"] = ADXIndicator(df_15m["high"], df_15m["low"], df_15m["close"]).adx()
            df_15m["atr"] = AverageTrueRange(df_15m["high"], df_15m["low"], df_15m["close"]).average_true_range()
            df_15m["volume_mean"] = df_15m["volume"].rolling(20).mean()

            last_row = df_15m.iloc[-1]
            score = compute_quality_score(last_row)
            entry_price = last_row["close"]
            quantity = calculate_quantity(budget_per_trade, entry_price, leverage)

            if score >= 6:
                result = {
                    "symbol": symbol,
                    "price": float(item["price"]),
                    "quality_score": score,
                    "signal": signal,
                    "quantity": quantity,
                    "entry": round(entry_price, 4),
                    "leverage": leverage,
                    "stop": round(entry_price - last_row["atr"] * 1.5, 4) if signal == "LONG" else round(entry_price + last_row["atr"] * 1.5, 4),
                    "tp": round(entry_price + last_row["atr"] * 2, 4) if signal == "LONG" else round(entry_price - last_row["atr"] * 2, 4)
                }
                results.append(result)
        except Exception as e:
            print(f"[!] שגיאה בניתוח {symbol}: {e}")
            continue

        time.sleep(0.3)

    results = sorted(results, key=lambda x: x["quality_score"], reverse=True)

    if results:
        best = results[0]
        print(f"🚀 ביצוע טרייד אוטומטי: {best['symbol']} | {best['signal']} | Entry={best['entry']}, SL={best['stop']}, TP={best['tp']} | Qty={best['quantity']} | Lev={best['leverage']}")
        execute_trade_live(
            symbol=best["symbol"],
            entry_price=best["entry"],
            stop_price=best["stop"],
            tp_price=best["tp"],
            side=best["signal"],
            leverage=best["leverage"]
        )
        executed_trade = best
        log_trade(best)

    return {
        "executed_trade": executed_trade,
        "all_candidates": results
    }






