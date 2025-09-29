# core/scheduler.py
from __future__ import annotations
import time, threading, json
from utils.symbols import WATCHLIST
from utils.datafeed import get_df  # תחזיר DF לפי tf/limit
from core.signal_fuser import fuse_signals
from utils.safety_controller import guarded_execute
from utils.config import cfg
from calibration.search import nightly_recalibrate

def scan_loop():
    while True:
        for symbol in WATCHLIST:
            for tf in ("5m","15m","1h"):
                df = get_df(symbol, tf, limit=600)
                out = fuse_signals(df, symbol=symbol, tf=tf)
                if out.get("ok"):
                    ctx = {
                        "symbol": symbol, "tf": tf, "side": out["side"],
                        "entry": out["entry"], "sl": out["sl"], "tp1": out["tp1"], "tp2": out["tp2"],
                        "quality": out["quality"], "atr": out["indicators"].get("alpha",{}).get("series",{}).get("atr", [0])[-1] if out["indicators"].get("alpha") else 0,
                        "reason": out["context"]["lead"]
                    }
                    try:
                        guarded_execute(ctx)
                    except Exception:
                        pass  # כבר דווח בהתרעות
        time.sleep(cfg.SCAN_INTERVAL)

def nightly_job():
    while True:
        # ירוץ פעם ב-24 שעות (אפשר CRON חיצוני אם תרצה)
        nightly_recalibrate()
        time.sleep(24*3600)

def start():
    threading.Thread(target=scan_loop, daemon=True).start()
    if cfg.CALIBRATION_NIGHTLY:
        threading.Thread(target=nightly_job, daemon=True).start()
