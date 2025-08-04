from dotenv import load_dotenv
import os

print("🔧 AlgoGPT Full Environment Check")

# טעינה ידנית של .env
env_loaded = load_dotenv()
print("📁 .env loaded:", env_loaded)

print("🔍 Checking environment variables...")

missing = []
required_vars = ["MAX_TRADE_BUDGET", "SCAN_INTERVAL", "BINANCE_API_KEY", "BINANCE_API_SECRET", "OPENAI_API_KEY"]

for var in required_vars:
    if not os.getenv(var):
        missing.append(var)

if missing:
    print(f"❌ Missing: {', '.join(missing)}")
else:
    print("✅ All required env vars are set.")


