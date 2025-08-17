# utils/config.py
import os

# דגלי ברירת מחדל – ניתנים לשינוי דרך ENV
EXECUTE_TRADES = str(os.getenv("EXECUTE_TRADES", "false")).lower() in ("1","true","yes","y","on")
BINANCE_SKIP_ACCOUNT_MUTATIONS = str(os.getenv("BINANCE_SKIP_ACCOUNT_MUTATIONS", "true")).lower() in ("1","true","yes","y","on")
BINANCE_FORCE_HEDGE_MODE = str(os.getenv("BINANCE_FORCE_HEDGE_MODE", "false")).lower() in ("1","true","yes","y","on")
MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "35"))

# SL/TP defaults
SLTP_MIN_PCT_FLOOR = float(os.getenv("SLTP_MIN_PCT_FLOOR", "0.003"))
SLTP_TP_PCT_FLOOR  = float(os.getenv("SLTP_TP_PCT_FLOOR",  "0.006"))
SLTP_ATR_SL_MULT   = float(os.getenv("SLTP_ATR_SL_MULT",   "1.5"))
SLTP_ATR_TP_MULT   = float(os.getenv("SLTP_ATR_TP_MULT",   "2.5"))











