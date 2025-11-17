#!/usr/bin/env python3
"""
🚨 Binance IP Ban Checker
Verifies if IP ban has been cleared after cooldown period.

Usage:
    python scripts/check_ban_status.py

Exit codes:
    0 = Ban cleared (200 OK)
    1 = Still banned (403/418/-1003)
    2 = Error/Unknown
"""

import os
import sys
import time
import hmac
import hashlib
from urllib.parse import urlencode
import requests

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BASE_URL = "https://fapi.binance.com"

def generate_signature(query_string: str) -> str:
    """Generate HMAC SHA256 signature for Binance API."""
    return hmac.new(
        BINANCE_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def check_ban_status():
    """
    Performs a single lightweight API call to check ban status.
    Uses GET /fapi/v2/balance (requires auth but minimal weight).
    """
    print("🔍 Checking Binance IP ban status...")
    print(f"📍 Endpoint: {BASE_URL}/fapi/v2/balance")
    print("")
    
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        print("❌ ERROR: BINANCE_API_KEY or BINANCE_API_SECRET not set")
        return 2
    
    # Prepare signed request
    timestamp = int(time.time() * 1000)
    params = {
        "timestamp": timestamp,
        "recvWindow": 5000
    }
    query_string = urlencode(params)
    signature = generate_signature(query_string)
    
    headers = {
        "X-MBX-APIKEY": BINANCE_API_KEY
    }
    
    url = f"{BASE_URL}/fapi/v2/balance?{query_string}&signature={signature}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        # Success - ban cleared
        if response.status_code == 200:
            print("✅ SUCCESS: Ban cleared!")
            print("📊 Status: 200 OK")
            print("🎉 IP is no longer banned")
            print("")
            print("💡 Next steps:")
            print("   1. Set EMERGENCY_KILL_SWITCH=0 in render.yaml")
            print("   2. Push to GitHub to trigger deployment")
            print("   3. Workers will resume with Safe-Boot throttling")
            return 0
        
        # Still banned
        elif response.status_code in [403, 418]:
            print("⚠️  STILL BANNED")
            print(f"📊 Status: {response.status_code}")
            print("⏰ Wait 60 more minutes and try again")
            print("")
            try:
                error_data = response.json()
                if "code" in error_data and error_data["code"] == -1003:
                    print(f"🚫 Binance says: {error_data.get('msg', 'Too many requests')}")
            except:
                print("📄 Response:", response.text[:200])
            return 1
        
        # Unknown error
        else:
            print(f"⚠️  UNEXPECTED STATUS: {response.status_code}")
            print(f"📄 Response: {response.text[:300]}")
            return 2
            
    except requests.exceptions.Timeout:
        print("⏰ TIMEOUT: Request took too long")
        print("💡 This might indicate network issues, not necessarily a ban")
        return 2
        
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        return 2

if __name__ == "__main__":
    exit_code = check_ban_status()
    sys.exit(exit_code)
