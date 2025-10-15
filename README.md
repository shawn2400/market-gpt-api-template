# 📊 AlgoGPT — LIVE Trading Orchestrator (FastAPI + Binance Futures)

מערכת מסחר אלגוריתמית בזמן-אמת, בנויה על FastAPI, עם אישורי אופס מאובטחים (HMAC/Anti-Replay/Bearer), ניהול חי מלא (TP/SL/BE/Trail/Ladder), אינטגרציית טלגרם דו־כיוונית, Redis, ומנגנוני HYBRID / MARKET / AUTO לביצוע.

**גרסה**: `2.18.0`  
**ארכיטקטורת ריצה**: Docker (Render), WS-only ל־Binance (עם Fallback חכם), ניטור Prometheus, Zero-Downtime Deploy.

---

## 🚀 עיקרי יכולות

- **אישורי אופס (Ops Approval):**
  - יצירת טיקט → לינק תצוגה + כפתורי אישור/דחייה בטלגרם.
  - **אישור חתום**: `/ops/approve/signed` עם HMAC (`X-Timestamp`, `X-Nonce`, `X-Signature`) + Anti-Replay ב־Redis.
  - ConfirmStore (TTL + Idempotency) למניעת כפילויות.

- **ביצוע טריידים (Execution Modes):**
  - `MARKET` — הזמנה מיידית.
  - `HYBRID` — שילוב Limit±band + Stop±band; הסלמה ל־MARKET כשנדרש.
  - `AUTO` — אם יש TP/SL → HYBRID; אחרת → MARKET.

- **ניהול חי (Live Trade Manager):**
  - **Breakeven (BE)** חכם עם Offset, **Trailing ATR** דינמי לפי ADX, **TP Ladder** (TP1/TP2/TP3), **Flip** חכם, Hedge Mode אמיתי.
  - **PnL Tracker + Reports** (CSV/PDF), מצטבר יומי.

- **טלגרם:**
  - Inline Approve/Reject עם Callback, אישורים חתומים בלינק, סנכרון דו־כיווני (מערכת ↔ טלגרם ↔ Redis).
  - פקודות: `/ping`, `/status`, `/positions`, `/pending`, `/ops/digest/now`, `/explain_on`, `/explain_off`.

- **Scoring & Gates:**
  - Multi-TF Analyzer (5m, 15m, 1h, 4h, 1d) עם RSI/MACD/EMA21-50/ADX/ATR/Volume/OBV/BB.
  - Quality Score (0–10), BTC-Anchor, Dynamic Scoring Range לפי ADX/Market Regime.

- **אוטונומיה וניהול דינמי:**
  - **Auto-Tune Engine** (ADX/ATR/SL/TP/Leverage) לפי מומנטום/איכות/עומסים.
  - **Dynamic Profile Switcher** (Conservative/Base/Aggressive/Extreme) בזמן אמת + עדכוני BE/TP/Splits/Trail.

- **בריאות וניטור:**
  - `/ultra/metrics` (Prometheus), `/readyz`, `/health` + **Ready Strict**.
  - **Guarder** (KillSwitch/PNL Caps), **Smart Digest** לטלגרם כל 3 שעות.

---

## 🧱 ארכיטקטורה — קבצים ושכבות

### שכבת ריצה (Docker)
- **Dockerfile** — Multi-stage (Builder → Runtime), התקנת תלויות, הקשחת סביבת ריצה, `tini`, `HEALTHCHECK`.
- **render.yaml** — שירות `web` ב־Render: דיסק קבוע, Env Vars, CORS/Redis/RateLimits/Anti-Replay/Secrets.
- **gunicorn_conf.py** — הגדרות Gunicorn (Workers/Timeouts/KeepAlive/Logging/Forwarded).
- **prestart.sh** — ניקוי/ולידציה של מפתחות Binance, הכנת תיקיות, בדיקת DNS לא־חוסמת.

### אפליקציה
- **main.py** — FastAPI ראשי:
  - תצורת CORS, הגנות Bearer לאנדפוינטים רגישים, רישום ראוטרים (AI/Trade/Backtest/Metrics/Telegram/Price/Scan/Manager/OPS).
  - חיבור Redis (Idempotency/Anti-Replay/Stores).
  - סורקים/מנהלים תקופתיים (Scheduler/Guarder/Manager/Scanner).
  - Reverse-proxy headers הקשחה (HSTS אם מופעל).

- **main_ultratop.py** — שכבת UltraTop (WS-only) להטענה/חיבור:
  - רישום **/ultra** (ברירת מחדל) עם `/ultra/health`, `/ultra/readyz`, `/ultra/readyz/strict`, `/ultra/meta`, `/ultra/meta/version`, `/ultra/metrics`.
  - **Runtime Prefs** דינמיים (PATCH דרך `/ultra/ops/runtime/prefs` עם HMAC).
  - **Policy DSL** (YAML) עם טעינה חמה: `/ultra/ops/policy/reload` (HMAC).
  - Prometheus (קאונטרים/היסטוגרמות/גייג'ים) + Middleware למדידת לטנסי.

- **Policies & Config**
  - `policies/dynamic_policy.yaml` — מדיניות ניהול חיה (BE/Trail/Ladder/Thresholds/Guards/Sizing/Regime).
  - `policies/ops_policy.yaml` — מדיניות אופס/תקשורת/קדרנציה/מגבלות/חלונות הקפאה/Canary/תקציבים/Guardrails.
  - `config/policy_schema.json` — JSON-Schema לאימות `dynamic_policy.yaml`.

- **כלי עזר / סקריפטים**
  - `scripts/smoke.sh` — בדיקות עשן (ללא תלות ב־jq בצד Makefile).
  - `scripts/sign_ultra.py` — יצירת חתימות HMAC (אופציונלי; אלטרנטיבה ל־Make targets).
  - `Makefile` — פקודות Dev/Build/Release/Ultra-Ops (כולל יצירת חתימות, שליחת בקשות חתומות, ועוד).

---

## 🔌 Endpoints עיקריים (דוגמאות)

> **הערה**: המסלולים בפועל תלויים באופן הרישום שלך ב־`main.py`/ראוטרים. להלן דוגמאות מסודרות לפי אזורים.

### בריאות וניטור
- `GET /health` — לייב בסיסי (Plain).
- `GET /readyz` — סטטוס כשירות כללי (כולל בדיקת Redis אם `REQUIRE_REDIS=1`).
- `GET /readyz/strict` — כמו `readyz` אך מחזיר 503 אם לא כשיר.
- `GET /ultra/health` — בריאות שכבת UltraTop.
- `GET /ultra/readyz`, `GET /ultra/readyz/strict`
- `GET /ultra/meta`, `GET /ultra/meta/version`
- `GET /ultra/metrics` — **מוגן Bearer** (`METRICS_BEARER`).

### אישורים ו־OPS
- `POST /ops/ticket` — יצירת טיקט אופס (לפי הפורמט אצלך).
- `GET /ops/ui/ticket` / `GET /ops/ui` — מסכי תצוגה/בקרה ציבוריים בהתאם ל־`SECURITY_PUBLIC_PATHS`.
- `POST /ops/approve` — אישור רגיל (Bearer).
- `POST /ops/approve/signed` — אישור חתום (HMAC: `X-Timestamp`, `X-Nonce`, `X-Signature`).
- `POST /ultra/ops/runtime/prefs` — עדכון Runtime Prefs (HMAC).
- `POST /ultra/ops/policy/reload` — טעינת Policy DSL מחדש (HMAC).

### טריידים וניהול
- `POST /trade/open` — פתיחת טרייד (MARKET/HYBRID/AUTO).
- `POST /trade/close` — סגירת טרייד קיים.
- `POST /manage-once` — ניהול חד־פעמי לפי מדיניות (תיקון: הנתיב מעודכן אצלך).
- `GET /positions` — סטטוס פוזיציות פעילות (אם נחשף).
- `GET /binance/status` — בדיקות חשבון/חיבור (אם נחשף).

### ציבוריים/פידים
- `GET /scan/public-now`, `GET /scan/public-topk`, `GET /public/sse-ticket` — בהתאם לרשימות ההיתר שלך (`SECURITY_PUBLIC_PATHS`/`PUBLIC_REQUIRE_BEARER`).

---

## ⚙️ קונפיגורציית ENV מרכזית

### אבטחה
- `API_BEARER_TOKEN` — לטובת GET-ים ציבוריים "קריאים בלבד" (לפי הגדרה).
- `PROTECT_APPROVE_ROUTES=1` — מחייב הגנה למסלולי אישור.
- `WEBHOOK_HMAC_SECRET` — חתימה ללינקי אישור (טלגרם/ווב).
- `OPS_SIGN_SECRET` — חתימה ל־`/ultra/ops/*`.
- `ANTI_REPLAY_ENABLE=1`, `SIGNED_TS_MAX_SKEW_SEC=60`, `SIGNED_NONCE_TTL_SEC=120` — הגנות Anti-Replay.
- `ENABLE_HSTS=1` — הפעלת HSTS אם רלוונטי.

### CORS
- `CORS_ALLOW_ORIGINS` — מקורות מורשים (רצוי דומיין הפובליק שלך).
- `CORS_ALLOW_HEADERS="*"` / `CORS_ALLOW_METHODS="*"` / `CORS_ALLOW_CREDENTIALS=0|1`
- (אופציונלי) `CORS_ALLOW_ORIGINS_STRICT` — לפרופילים אולטרה-מחמירים.

### Redis
- `REQUIRE_REDIS=1`, `REDIS_URL=...`
- `REDIS_NAMESPACE="ops-supervisor-web"`, `USE_REDIS_IDEM=1`, `IDEM_TTL_SEC=90`
- TLS: `REDIS_SSL_CERT_REQS=required`, `REDIS_SSL_CA_CERTS=/etc/ssl/certs/ca-certificates.crt`

### בורסה (Binance)
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `DEFAULT_MARKET=futures`
- `POSITION_MODE_OVERRIDE=hedge|oneway`, `BINANCE_WORKING_TYPE=MARK_PRICE`
- `BINANCE_FUTURES_HTTP_BASE`, `BINANCE_FUTURES_WS_BASE`
- ביצועים: `BINANCE_HTTP_TIMEOUT`, `BINANCE_RECV_WINDOW`, `BINANCE_MAX_RETRIES`, `LISTENKEY_KEEPALIVE_SEC`, `WS_KEEPALIVE_SEC`.

### סורק/אינדיקטורים
- `SCAN_SOURCE=binance-futures`, `UNIVERSE_MODE=exchange`
- `SCAN_INTERVALS="5m,15m,1h,4h"`, `SCAN_MAX_SYMBOLS=150`, `TOP_SYMBOLS=80`
- `INDICATOR_INTERVALS="15m,1h,4h,1d"`, `ADX_MIN=20`, `FEAT_*` למגוון שערים.

### ניהול טריידים
- **TP/SL/Ladder/Trail/BE**: `NATIVE_TPSL_ENABLE`, `SL_MONOTONIC`, `TRAIL_ATR_MULT`, `TP_MAX_LADDERS`, `TP_BE_ONLY_AFTER_TP1`, `TP_BE_OFFSET_BPS`, `BE_ARM_PCT`, `BE_GUARD_EVERY_SEC`, ועוד.
- **Real-time Trailing Loop**: `TRAIL_RT_*` — מקסימום סמלים, תדירות, מקור מחיר (MARK_PRICE), מגבלות Callback.

### Guarder/Risk/Health
- `DAILY_LOSS_CAP_USDT`, `KILL_ON_CAP=1`, `PRICE_PROTECT=1`
- `HEALTH_PRICE_MAX_AGE`, `OPS_DIGEST_INTERVAL_HOURS`, `OPS_HEARTBEAT_ENABLE`

### מסמכים/DB/מדדים
- `DATABASE_URL=sqlite:////app/data/algogpt.db`
- `METRICS_ENABLE=true`, `PNL_TRACKING=true`
- `PARAMS_DIR="params/optimized"`

---

## 🧭 מדיניות (Policies)

### `policies/dynamic_policy.yaml`
- `breakeven` — `enable`, `only_after_tp1`, `offset_bps`, `guard_every_sec`, `arm_pct`.
- `trailing` — `atr_mult`, `callback_min_pct`, `callback_max_pct`, `freeze_on_pullback`.
- `ladder.tp` — `enable`, `splits`, `targets_pct`, `place_native`.
- `ladder.sl` — `enable`, `atr_mult`, `place_native`.
- `thresholds` / `guards` / `sizing` / `regime`.

### `config/policy_schema.json`
- JSON-Schema שמאמת שדות חובה ומסגרות ערכים עבור `dynamic_policy.yaml`.

### `policies/ops_policy.yaml`
- **MASTER**/**NOTIFY**/**PROFILES**/**SCHEDULE**/**GATES**/**QUALITY_GATES**/**CHANGE_APPROVAL**
- **APPROVAL_ENDPOINTS**/**APPROVAL_FLOW**/**FLAGS**/**FREEZE_WINDOWS**/**SLO_GUARD**/**BUDGETS**
- Canary, Innovation Watch, Exchange Guard, Chaos Lite, DR, Postmortem ועוד.

---

## 🧩 לוגיקה מודולרית (מחלקות/רכיבים מרכזיים)

> השמות הכלליים מתארים את התפקיד; בפועל מימשת אותם בקבצי `routes.*`, `services.*`, `utils.*` וכד'.

- **TradeExecutor**  
  מקבל החלטת כניסה (כולל מצב HYBRID/MARKET/AUTO), מבצע הזמנות בהתאם לפילטרי בורסה, גודל כמות (Auto QTY), ו־OCO/Native TP/SL אם מוגדר.

- **TradeManager**  
  מיישם ניהול חי: עדכוני SL/TP/Trail/BE בזמן אמת, Re-issue לפי Policy (cancel_replace), חישובי ATR/ADX, Flip חכם, הגנות שוק (Spread/Depth/ATR-Max).

- **Scanner**  
  מאגד נתונים מ־WS (ולפי צורך REST fallback), מחשב אינדיקטורים על Multi-TF, קובע **Quality Score**, ומגיש מועמדים ל־Approval Gate (טלגרם).

- **Approvals**  
  יצירה/ניהול טיקטים; אישור רגיל (Bearer) או חתום (HMAC/Anti-Replay). ConfirmStore + TTL מונעים כפילויות; דוחות Digest.

- **TelegramBridge**  
  רישום webhook, שליחת הודעות טרייד בלבד או לפי מדיניות; Inline Buttons עם Callback; Admin-only אם נדרש.

- **RedisStores**  
  Anti-Replay (`nonce`), Idempotency Keys ל־OPS/Orders, ConfirmStore, Rate-Limit/Quota, בריאות/Cache.

- **UltraTop Runtime**  
  Prefs דינמיים (הדלקה/כיבוי יכולות בזמן אמת), טעינת Policy חמה, Prometheus metrics, WS-loop placeholder להחלפה במנהל ה־WS שלך.

---

## 🛠️ הרצה מקומית (DEV)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export PORT=10000
export API_BEARER_TOKEN=dev_token
export OPS_SIGN_SECRET=dev_secret
export METRICS_BEARER=dev_metrics

# ריצה חמה
uvicorn main:app --reload --host 0.0.0.0 --port $PORT




















