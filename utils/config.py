# utils/config.py
import os

# ------------ API KEYS ------------
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "").strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# ------------ SERVER CONFIG ------------
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ------------ TRADING CONFIG ------------
AUTO_RUN = os.getenv("AUTO_RUN", "false").lower() in ("1", "true", "yes")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "60"))  # seconds between scans
MIN_QUALITY_SCORE = int(os.getenv("MIN_QUALITY_SCORE", "6"))
MAX_TRADE_BUDGET = float(os.getenv("MAX_TRADE_BUDGET", "100"))

# Optional filters
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "1000000"))
TRENDING_ONLY = os.getenv("TRENDING_ONLY", "false").lower() in ("1", "true", "yes")

# ------------ RESPONSE LIMIT ------------
# ברירת מחדל: 1MB
RESPONSE_MAX_BYTES = int(os.getenv("RESPONSE_MAX_BYTES", str(1024 * 1024)))

# ------------ BINANCE ENDPOINTS ------------
# Futures (ברירת מחדל)
BINANCE_FUTURES_BASE = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

# Spot
BINANCE_SPOT_BASE = os.getenv("BINANCE_SPOT_HTTP_BASE", "https://api.binance.com")

# ------------ SAFETY CHECKS ------------
if not API_BEARER_TOKEN:
    print("⚠️ Warning: API_BEARER_TOKEN is missing (all routes will be open).")

if not OPENAI_API_KEY:
    print("⚠️ Warning: OPENAI_API_KEY missing → AI features disabled.")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    print("⚠️ Warning: Binance keys missing → trading may not work.")

print(f"✅ AlgoGPT config loaded | Model={OPENAI_MODEL} | Spot={BINANCE_SPOT_BASE} | Futures={BINANCE_FUTURES_BASE}")


















