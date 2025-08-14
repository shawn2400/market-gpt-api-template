# utils/health_check.py
from __future__ import annotations

import os
import json
from typing import Dict, Any

from dotenv import load_dotenv
load_dotenv(override=False)

from utils import config
from utils.binance_client import get_client, ping_and_info
from utils.ai_client import ai_healthcheck

REQUIRED_ENV = [
    # שדות חובה "קשים" ניתן לרכך בהתאם לסביבת הרצה
    # שימו לב: לא נכשל אם הם חסרים — רק מדווחים.
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPENAI_API_KEY",
    "CRYPTO_PANIC_API_KEY",
    "ALERT_EMAIL_ADDRESS",
    "ALERT_EMAIL_PASSWORD",
]

CRITICAL_FILES = [
    "watchlist.json",
    "open_trades.json",
    "pnl_tracker.json",
]


def check_env() -> bool:
    print("🔎 בדיקת משתני סביבה:")
    all_present = True
    for k in REQUIRED_ENV:
        v = os.getenv(k, "")
        if not v:
            print(f"⚠️  חסר: {k}")
            all_present = False
        else:
            print(f"✅ {k} — מוגדר")
    return all_present


def check_binance() -> bool:
    print("\n🔎 בדיקת Binance:")
    try:
        ok_ping = ping_and_info()
        print(f"✅ ping: {ok_ping}")
    except Exception as e:
        print(f"⚠️ ping נכשל: {e}")
        ok_ping = False

    # אם אין מפתחות — נסתפק ב־public-only
    key_missing = not (getattr(config, "BINANCE_API_KEY", "") and getattr(config, "BINANCE_API_SECRET", ""))
    if key_missing:
        print("ℹ️  מפתחות Binance לא הוגדרו — מצב Public-Only (market data).")
        return ok_ping

    try:
        client = get_client()
        # קריאה קלה שמצריכה הרשאות; אם מצליחה — הכל טוב.
        _ = client.futures_account_balance()
        print("✅ Futures account: OK")
        return True and ok_ping
    except Exception as e:
        print(f"❌ גישה לחשבון Futures נכשלה: {e}")
        return False


def check_ai() -> bool:
    print("\n🔎 בדיקת OpenAI/Azure OpenAI:")
    try:
        res = __import__("asyncio").get_event_loop().run_until_complete(ai_healthcheck())
    except RuntimeError:
        # אם הלופ כבר רץ (סקריפט בתוך uvicorn), נבצע ראנר זמני
        import asyncio
        async def _go():
            return await ai_healthcheck()
        res = asyncio.run(_go())

    ok = bool(res.get("ok"))
    mode = res.get("mode")
    model = res.get("model")
    base = res.get("base")
    if ok:
        print(f"✅ AI OK | mode={mode} model={model} base={base}")
    else:
        print(f"⚠️ AI בעייתי | {res}")
    return ok


def _ensure_json(path: str, default):
    if os.path.exists(path):
        print(f"✅ קיים: {path}")
        return
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        print(f"🆕 נוצר: {path}")
    except Exception as e:
        print(f"❌ כשל ביצירת {path}: {e}")


def check_files() -> bool:
    print("\n🔎 בדיקת קבצים קריטיים:")
    ok = True
    # ברירות מחדל סבירות
    defaults: Dict[str, Any] = {
        "watchlist.json": [
            {"symbol": "BTCUSDT", "direction": "LONG", "quality_score": 8},
            {"symbol": "ETHUSDT", "direction": "LONG", "quality_score": 7},
        ],
        "open_trades.json": [],
        "pnl_tracker.json": {},
    }
    for fname in CRITICAL_FILES:
        try:
            _ensure_json(fname, defaults.get(fname, {}))
        except Exception:
            ok = False
    return ok


def main() -> int:
    print("=== Health Check ===")
    env_ok = check_env()
    binance_ok = check_binance()
    ai_ok = check_ai()
    files_ok = check_files()

    all_ok = (binance_ok and ai_ok and files_ok)
    # אין צורך להיכשל על משתנים חסרים אם הרצה דמו/ציבורית
    if env_ok:
        print("ℹ️  ENV ברמה טובה (ייתכן שחלק חסר אך נסבל).")

    if all_ok:
        print("\n✅ המערכת מוכנה להרצה!")
        return 0
    else:
        print("\n❌ יש בעיות — בדוק את ההודעות למעלה.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

