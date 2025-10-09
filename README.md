# 📊 AlgoGPT — LIVE Trading Orchestrator (FastAPI + Binance Futures)

מערכת מסחר אלגוריתמית בזמן-אמת עם FastAPI, אישורי אופס מאובטחים (HMAC/Anti-Replay/Bearer), ניהול חי (TP/SL/BE/Trail/Ladder), טלגרם, Redis, ו-HYBRID/ MARKET / AUTO flow.

---

## 🚀 עיקרי יכולות
- **אישור אופס**: יצירת טיקט → לינק תצוגה + כפתורי אישור/דחייה בטלגרם (מוגן Bearer).
- **אישור חתום**: `/ops/approve/signed` עם HMAC (X-Timestamp, X-Nonce, X-Signature) + Anti-Replay ב-Redis.
- **ביצוע טרייד**:
  - `MARKET` — הזמנה מיידית.
  - `HYBRID` — Limit±band + Stop±band, Escalate ל-MARKET כשצריך.
  - `AUTO` — אם יש TP/SL → HYBRID, אחרת → MARKET.
- **ניהול חי**: TP/SL בליידר, Breakeven, Trailing (ATR), ו-Smart Manage אחרי אישור.
- **טלגרם**: הודעות טריידים בלבד (או לפי מדיניות), רישום webhook אוטומטי.
- **Redis**: אחסון טיקטים/אנטי-ריפליי/איידמפוטנציה/דיג׳סטים.
- **בריאות**: `/readyz` בודק Redis כש-`REQUIRE_REDIS=1`.

---

## 🧱 ארכיטקטורה (בקצרה)
- `main.py` — FastAPI, CORS, הקשחות, טלגרם, Redis, Signed Approve, periodic manager/guarder/scanner.
- `routes.manager` — `POST /manage-once` (תיקון נתיב), ניהול פוזיציות.
- `utils.*` — חישוב כמויות, שמירה על סטופים, בניית מזהי הזמנות, וכו׳.

---

## ⚙️ קונפיג (ENV) עיקרי
- **אבטחה**:  
  `PROTECT_APPROVE_ROUTES=1`, `API_BEARER_TOKEN`, `WEBHOOK_HMAC_SECRET`, `OPS_SIGN_SECRET`,  
  `SIGNED_TS_MAX_SKEW_SEC=60`, `SIGNED_NONCE_TTL_SEC=120`.
- **Redis**:  
  `REQUIRE_REDIS=1`, `REDIS_URL=...`, `REDIS_NAMESPACE=ops-supervisor-web`.
- **טלגרם**:  
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_AUTO_WEBHOOK=1`.
- **בינאנס**:  
  `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `POSITION_MODE_OVERRIDE=oneway`, `DEFAULT_MARKET=futures`.
- **ניהול חי/הגנות**:  
  `TP_LADDER_ON_APPROVE=1`, `LADDER_TP_DEFAULT_PCTS=1.8,3.2,5.5`, `LADDER_TP_DEFAULT_SPLITS=0.4,0.35,0.25`,  
  `SL_MONOTONIC=1`, `TRAIL_ATR_MULT=1.5`, `TP_BE_ONLY_AFTER_TP1=1`, `TP_BE_OFFSET_BPS=8`.

---

## 🛠️ הרצה מקומית (DEV)
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PORT=10000
uvicorn main:app --reload --port $PORT





















