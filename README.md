# 📊 AlgoGPT — LIVE Trading Orchestrator (FastAPI + Binance Futures)

מערכת מסחר אלגוריתמית בזמן-אמת, בנויה על FastAPI, עם אישורי אופס מאובטחים (HMAC / Anti-Replay / Bearer), ניהול חי מלא (TP/SL/BE/Trail/Ladder), אינטגרציית טלגרם דו־כיוונית, Redis, ומנגנוני **HYBRID / MARKET / AUTO** לביצוע.

**גרסה:** `2.18.0`  
**ארכיטקטורת ריצה:** Docker (Render), WS-only ל-Binance (עם fallback), ניטור Prometheus, Zero-Downtime Deploy.

---

## 🚀 יכולות מרכזיות

- **אישורי אופס (Ops Approval)**
  - יצירת טיקט → לינק תצוגה + כפתורי אישור/דחייה בטלגרם.
  - **אישור חתום**: `/ops/approve/signed` עם HMAC (`X-Timestamp`, `X-Nonce` אופציונלי, `X-Signature`) + Anti-Replay ב-Redis.
  - ConfirmStore (TTL + Idempotency) למניעת כפילויות ו־replays.

- **ביצוע טריידים (Execution Modes)**
  - `MARKET` — הזמנה מיידית.
  - `HYBRID` — שילוב Limit±band + Stop±band, עם הסלמה ל-MARKET כשנדרש.
  - `AUTO` — אם קיימים TP/SL → HYBRID; אחרת → MARKET.

- **ניהול חי (Live Trade Manager)**
  - **Breakeven (BE)** חכם עם Offset ו־arm/guard, **Trailing ATR** דינמי לפי ADX/רז’ים, **TP Ladder** (TP1/TP2/TP3), **Flip** חכם, Hedge Mode אמיתי.
  - **PnL Tracker + Reports** (CSV/PDF), מצטבר יומי.

- **טלגרם**
  - Inline Approve/Reject עם Callback, אישורים חתומים בלינק (HMAC), סנכרון דו-כיווני (מערכת ↔ טלגרם ↔ Redis).
  - פקודות לדוגמה: `/ping`, `/status`, `/positions`, `/pending`, `/ops/digest/now`, `/explain_on`, `/explain_off`.

- **Scoring & Gates**
  - Multi-TF Analyzer (5m, 15m, 1h, 4h, 1d) עם RSI/MACD/EMA(21/50)/ADX/ATR/Volume/OBV/BB.
  - Quality Score (0–10), BTC-Anchor, Dynamic Scoring Range לפי ADX/Market Regime.

- **אוטונומיה וניהול דינמי**
  - Auto-Tune Engine (ADX/ATR/SL/TP/Leverage) לפי מומנטום/איכות/עומסים.
  - Dynamic Profile Switcher (Conservative/Base/Aggressive/Extreme) בזמן אמת.

- **בריאות וניטור**
  - `/ultra/metrics` (Prometheus, **מוגן Bearer**), `/readyz`, `/readyz/strict`, `/health`.
  - Guarder (KillSwitch/PNL Caps), Smart Digest לטלגרם (ברירת מחדל: כל 3 שעות).

---

## 🧱 מבנה הפרויקט (Layers & Files)

### Runtime (Docker)
- **Dockerfile** — Multi-stage (Builder → Runtime), התקנת תלויות, `tini`, `HEALTHCHECK`, הרשאות, שמירת גרסה ל־`/app/VERSION`.
- **render.yaml** — שירות `web` ב-Render: דיסק קבוע, Env Vars, CORS/Redis/RateLimits/Anti-Replay/Secrets.
- **gunicorn_conf.py** — הגדרות Gunicorn: Workers/Timeouts/KeepAlive/Logging/Forwarded headers, tmp וכו’.
- **prestart.sh** — ניקוי/ולידציה של Binance Keys (אורך 64), תיקיות, בדיקת DNS לא-חוסמת.

### אפליקציה
- **main.py** — FastAPI ראשי:
  - CORS, הקשחות Bearer למסלולים רגישים, רישום ראוטרים (AI/Trade/Backtest/Metrics/Telegram/Price/Scan/Manager/Ops).
  - Redis (Idempotency/Anti-Replay/Stores).
  - סורקים/מנהלים תקופתיים (Scheduler/Guarder/Manager/Scanner).
  - HSTS (אם `ENABLE_HSTS=1`), ו־Security Public Paths/Prefixes לפי ENV.

- **main_ultratop.py** — שכבת UltraTop (ניתן להטמיע בתוך main או להריץ כסטנד־אלון)
  - מסלולים: `/ultra/health`, `/ultra/readyz`, `/ultra/readyz/strict`, `/ultra/meta`, `/ultra/meta/version`, `/ultra/metrics` (**Bearer**).
  - **Runtime Prefs** דינמיים: `POST /ultra/ops/runtime/prefs` (HMAC).
  - **Policy Hot-Reload**: `POST /ultra/ops/policy/reload` (HMAC).
  - Prometheus registry פרטי + Middleware ל-latency/req count.

### Policies & Config
- **policies/dynamic_policy.yaml** — BE/Trail/Ladder/Thresholds/Guards/Sizing/Regime.
- **policies/ops_policy.yaml** — MASTER/NOTIFY/PROFILES/SCHEDULE/GATES/QUALITY/CHANGE_APPROVAL/APPROVAL_FLOW/… כולל Canary/Freeze/Budgets/DR.
- **config/policy_schema.json** — JSON-Schema לאימות dynamic policy.

### Scripts & Tooling
- **scripts/smoke.sh** — בדיקות עשן מהירות (ללא תלות ב־jq בצד Makefile).
- **scripts/hit_public_feed.sh** — קריאות לפידים ציבוריים (Bearer אופציונלי).
- **scripts/approve_via_telegram.sh** — אישור/דחייה ל־ticket דרך `/ops/approve/signed` עם HMAC.
- **scripts/sign_ultra.py** — יצירת חתימת HMAC ושליחה ל־`/ultra/ops/*`.
- **Makefile** — פקודות Dev/Build/Release/Ultra-Ops (כולל יעדי `public`/`approve`).

---

## 🔌 Endpoints (סקירה תמציתית)

> שמות/נתיבים עשויים להשתנות לפי הרישום שלך. אלו המקובלים בפרויקט:

### בריאות וניטור
- `GET /health` — בסיסי.
- `GET /readyz` — סטטוס כללי (כולל Redis אם `REQUIRE_REDIS=1`).
- `GET /readyz/strict` — 200/503 לפי כשירות.
- `GET /ultra/health`, `GET /ultra/readyz`, `GET /ultra/readyz/strict`
- `GET /ultra/meta`, `GET /ultra/meta/version`
- `GET /ultra/metrics` — **חובה Bearer** (`METRICS_BEARER`).

### אישורים ו־OPS
- `POST /ops/ticket` — יצירת טיקט (פורמט פנימי).
- `GET /ops/ui`, `GET /ops/ui/ticket` — תצוגות ציבוריות (לפי SECURITY_PUBLIC_PATHS).
- `POST /ops/approve` — אישור רגיל (Bearer).
- `POST /ops/approve/signed` — **אישור חתום** (HMAC + Anti-Replay).
- `POST /ultra/ops/runtime/prefs` — עדכון runtime prefs (HMAC).
- `POST /ultra/ops/policy/reload` — טעינת Policy (HMAC).

### טריידים וניהול
- `POST /trade/open`, `POST /trade/close`
- `POST /manage-once` — ניהול חד־פעמי לפי מדיניות.
- `GET /positions` — סטטוס פוזיציות (אם נחשף).
- `GET /binance/status` — בריאות/חיבור/הרשאות (אם נחשף).

### ציבוריים/פידים
- `GET /scan/public-now`, `GET /scan/public-topk`, `GET /topk`, `GET /topk.csv`, `GET /public/sse-ticket`
- ייתכן **Bearer** אם `PUBLIC_REQUIRE_BEARER=1`.

---

## ⚙️ Environment (מפתחות עיקריים)

### אבטחה
- `API_BEARER_TOKEN` — לטובת GET-ים מוגנים “קריאה בלבד”.
- `PROTECT_APPROVE_ROUTES=1` — מגֵן מסלולי אישור.
- `WEBHOOK_HMAC_SECRET` — חתימת לינקי אישור (ווב/טלגרם).
- `OPS_SIGN_SECRET` — חתימה למסלולי `/ultra/ops/*`.
- `ANTI_REPLAY_ENABLE=1`, `SIGNED_TS_MAX_SKEW_SEC=60`, `SIGNED_NONCE_TTL_SEC=120`.
- `ENABLE_HSTS=1` — HSTS.

### CORS
- `CORS_ALLOW_ORIGINS="https://algogpt-docker.onrender.com"` (דוגמה), `CORS_ALLOW_HEADERS="*"`, `CORS_ALLOW_METHODS="*"`, `CORS_ALLOW_CREDENTIALS=0|1`.

### Redis
- `REQUIRE_REDIS=1`, `REDIS_URL=...`, `REDIS_NAMESPACE="ops-supervisor-web"`.
- TLS: `REDIS_SSL_CERT_REQS=required`, `REDIS_SSL_CA_CERTS=/etc/ssl/certs/ca-certificates.crt`.

### Binance
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `DEFAULT_MARKET=futures`.
- `POSITION_MODE_OVERRIDE=hedge|oneway`, `BINANCE_WORKING_TYPE=MARK_PRICE`.
- `BINANCE_FUTURES_HTTP_BASE`, `BINANCE_FUTURES_WS_BASE`, ועוד.

### Scanner/Indicators
- `SCAN_SOURCE=binance-futures`, `UNIVERSE_MODE=exchange`.
- `SCAN_INTERVALS="5m,15m,1h,4h"`, `SCAN_MAX_SYMBOLS=150`, `TOP_SYMBOLS=80`.
- `INDICATOR_INTERVALS="15m,1h,4h,1d"`, `ADX_MIN=20`, `FEAT_*`.

### ניהול טריידים
- **TP/SL/Ladder/Trail/BE**: `SL_MONOTONIC`, `TRAIL_ATR_MULT`, `TP_MAX_LADDERS`, `TP_BE_ONLY_AFTER_TP1`, `TP_BE_OFFSET_BPS`, `BE_ARM_PCT`, `BE_GUARD_EVERY_SEC`, …
- **Real-time Trailing Loop**: `TRAIL_RT_*` — אינטרוול, מקור מחיר, מגבלות callback, כמות סמלים.

### Guarder/Risk/Health
- `DAILY_LOSS_CAP_USDT`, `KILL_ON_CAP=1`, `PRICE_PROTECT=1`.
- `OPS_DIGEST_INTERVAL_HOURS`, `OPS_HEARTBEAT_ENABLE`.

### Misc/DB/Metrics
- `DATABASE_URL=sqlite:////app/data/algogpt.db`
- `METRICS_ENABLE=true`, `PNL_TRACKING=true`
- `PARAMS_DIR="params/optimized"`

---

## 🔐 מודל אבטחה — HMAC/Bearer/Anti-Replay (דוגמאות שימוש)

### חתימה ל־/ultra/ops/runtime/prefs (Makefile)
```bash
# עריכת פרמטרים בזמן ריצה:
make ultra-prefs \
  OPS_SIGN_SECRET='your_ops_secret' \
  ULTRA_HOST='https://algogpt-docker.onrender.com' \
  BODY='{"patch":{"TP_DYNAMIC_ENABLE":1,"ENTRY_CONF_MIN":0.7}}'

















