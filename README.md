# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת (Binance Futures / Spot / Grid)

**AlgoGPT** היא מערכת מסחר אלגוריתמית מבוססת **FastAPI** עם אינטגרציה ל־**Binance**, ניתוח טכני רב־שכבתי, ניהול חי דטרמיניסטי (SL/TP/Breakeven/Trailing), ו**סוכן GPT** קשוח ומוכוון־מטרה.

---

## 🚀 יכולות
- 📈 **ניתוח טכני**: EMA21/EMA50, ATR, מומנטום קצר (3–4 נרות), ועוד (RSI/MACD/BB/OBV/FVG – לבחירה).
- 🧭 **Gate איכות**: בדיקות מגמה/מומנטום/ATR/נפח לפני כניסה.
- 🎯 **ניהול חי**: TP/SL בליידר (MARKET/LIMIT), Breakeven ו־Trailing (דרך קונפיג).
- 🤖 **Agent GPT**: ניתוח AI, פלט JSON אחיד, `reason_code`.
- 📊 **דוחות**: סיכומי טרייד אוטומטיים, דיווחי Daily/Weekly/Monthly בטלגרם.
- 🛡️ **היגיינת Orders**: Reduce-Only, ביטול TP/SL ישנים לפני חימוש חדשים.
- 🔐 **אישור אופס**: טיקט→קישור אישור/דחייה בטלגרם, HMAC פנימי לחתימה.

---

## 🧱 ארכיטקטורה קצר
- `main.py` — FastAPI, אמצעי אבטחה/לוגינג, public paths, CORS, מדדים, warmup, auto webhook לטלגרם, לולאת ניהול פתוחות אופציונלית.
- `routes/ops_approve.py` — יצירת טיקטים, אישור/דחייה (עם URL), ביצוע בפועל (MARKET / HYBRID / AUTO), הודעות לטלגרם.
- `routes/ops_ui.py` — דף HTML קליל (3 כפתורים: MARKET/HYBRID/AUTO) שמייצר טיקט עם `[mode: ...]`.
- `routes/ui.py` — הגשת דשבורד סטטי `static/dashboard/index.html`.
- `app/trade_executor.py` — המנוע: הקצאה, חישוב כמות, HYBRID (Limit+Stop+Escalate), חימוש TP/SL, בדיקות סניטי ואיידמפוטנציה, ConfirmStore (Redis/זיכרון).

---

## ⚙️ משתני סביבה (ENV) — “מה כל הגדרה עושה” (העיקריים)
> כל **בוליאני**: `1/true/yes/on` = דלוק, כל השאר = כבוי.

### ליבה / FastAPI
- `PORT` — פורט שרת (ברירת מחדל: `10000`).
- `LOG_LEVEL` — `DEBUG|INFO|WARNING|ERROR`. קובע וורבוזיות לוגים.
- `RESPONSE_MAX_BYTES` — מקסימום גודל תגובה (בייטים) לפני חסימה.
- `CORS_ALLOW_ORIGINS` — רשימת דומיינים מופרדים בפסיקים (או `*`) ל־CORS.
- `CORS_ALLOW_CREDENTIALS` — מאפשר Cookies/Auth ב־CORS כאשר מקור לא `*`.

### Public/אבטחה
- `SECURITY_PUBLIC_STATUS` — אם `1`, אנו מאפשרים public paths דיפולט.
- `SECURITY_PUBLIC_PATHS` — נתיבים ספציפיים לפתיחה (מופרדים בפסיקים).
- `SECURITY_PUBLIC_PREFIXES` — פרפיקסים לפתיחה (כמו `/static/`, `/price`).
- `API_BEARER_TOKEN` / `API_TOKEN` — מפתח API לצריכת ה־API (Authorization: Bearer).
- `WEBHOOK_HMAC_SECRET` — סוד HMAC ל־`/ops/approve/signed`.

### Binance
- `BINANCE_API_KEY`, `BINANCE_API_SECRET` — מפתחות API לחשבון.
- `DEFAULT_INTERVAL` — ברירת המחדל לסריקת ק־ליינים (למשל `15m`).

### טלגרם
- `TELEGRAM_BOT_TOKEN` — טוקן בוט.
- `TELEGRAM_CHAT_ID` — ערוץ/משתמש לקבלת הודעות (מספרי/שם).
- `TELEGRAM_AUTO_WEBHOOK` — רישום webhook אוטומטי בבוט.
- `WEBHOOK_HMAC_SECRET` — (ראו “אבטחה”) לבקשות פנימיות חתומות.

### Redis
- `REDIS_URL` — אם קיים, נשתמש בשביל ConfirmStore/Idempotency/טיקטים.
- `OPS_TICKET_TTL_SEC` — זמן פקיעת טיקט (ברירת מחדל: `1800` שניות).

### מנוע טריידים — הגנות וזרימות
- `ALLOW_MARKET_ENTRY` — ב־HYBRID, האם להסלים ל־MARKET אם צריך.
- `ENTRY_BAND_BPS` — מרחק Limit סביב מחיר יעד (ב־bps; 1%=100 bps).
- `STOP_BAND_BPS` — מרחק Stop סביב יעדי כניסה (ב־bps).
- `ESCALATE_AFTER_SEC` — אחרי כמה שניות לשקול הסלמה ל־MARKET.
- `ESCALATE_SLIPPAGE_BPS` — צריך “גלישה” ≥ סף זה + gate איכות → הסלמה.
- `PERCENT_PRICE_GUARD_BPS` — הגנה על פער מחיר מול ref לפני שליחה.
- `SLIPPAGE_GUARD_BPS` — guard בזמן בניית HYBRID.
- `POST_FILL_SANITY_BPS` — אחרי Fill: אם הפער מול Mark > סף → rollback.
- `ENFORCE_POST_FILL_SANITY` — לאכוף rollback במקרה חריג.

### Gate/איכות, תקציב/מינוף דינמיים
- `FEAT_QUALITY_ENFORCE` — אם gate נכשל → דחייה.
- `MIN_QUALITY_SCORE`, `MIN_QUALITY_FALLBACK`, `QUALITY_DEFAULT` — טיוב סף/ברירת מחדל.
- `MAX_ATR_PCT` — ATR% מקסימלי להיתר כניסה.
- `BUDGET_DYNAMIC_ENABLE` — כיבול תקציב דינמי.
- `BUDGET_USE_BALANCE` — שימוש ב־available USDT להקצאה יחסית.
- `BUDGET_DYNAMIC_RISK_PCTS` — `"1.5,3,5"` (לפי איכות).
- `DYN_LEVERAGE_ENABLE` — מינוף דינמי לפי ADX.
- `LEV_ADX_MAP_JSON` — מפה ADX→מינוף (JSON), למשל `{"30":15,"25":12,"20":9,"0":7}`.
- `LEVERAGE_SYMBOL_CAPS` — Caps פר-סימבול (JSON).

### TP/SL Ladder
- `LADDER_TP_ENABLE` / `LADDER_SL_ENABLE` — להפעיל חימוש מטרות/סטופ.
- `LADDER_TP_KIND` — `"TAKE_PROFIT_MARKET"` (דיפולט) או `"TAKE_PROFIT"`.
- `LADDER_TP_DEFAULT_PCTS` — אחוזי מטרות כברירת מחדל, `"1.8,3.2,5.5"`.
- `LADDER_TP_DEFAULT_SPLITS` — חלוקת כמויות `"0.4,0.35,0.25"`.
- `LADDER_SL_DEFAULT_PCTS` — אחוזי SL כברירת מחדל (מעט, שמרני).

### אישור / Idempotency
- `ENFORCE_APPROVAL_ALWAYS` — לדרוש אישור טלגרם לפני ביצוע חי.
- `CONFIRM_TTL_SEC` — חלון זמן לאישור.
- `IDEMPOTENCY_TTL_SEC` — חלון חסימת כפילויות (שניות).

---

## 🧩 מצבי פעולה (mode) — ליבה + נגזרות (קלים לעומס)

הוספת תג ל־`note`, לדוגמה:  
`[mode: MARKET] כניסה מהירה`  
`[mode: HYBRID] כניסה עם Limit±band + Stop±band ואפשרות הסלמה`  
`[mode: AUTO] המערכת בוחרת HYBRID/ MARKET לפי תנאים פשוטים`

**ליבה (ממומש):**
- `MARKET` — הזמנה מיידית (פשוטה).
- `HYBRID` — Limit+Stop (עם Escalate ל־MARKET כשהגיוני).
- `AUTO` — אם סיפקת TP/SL → HYBRID, אחרת → MARKET.

**נגזרות (דגלים רעיוניים, קלים לחיבור):**
- `MARKET+TP` / `MARKET+SL` / `HYBRID+TP` / `HYBRID+SL` — חימוש חלקי.
- `MARKET+REDUCE` — פעולה כ־reduceOnly (לסגירת חלק/כולל).
- `TPKIND: MARKET|LIMIT` — קובע סוג מטרות.
- `TPSPLIT: a,b,c` — חלוקת כמויות בין מטרות.
> חלק מנגזרות אלו ניתנות כבר היום דרך פרמטרים בטיקט (`tp_targets`, `sl_targets`, `tp_splits`, `reduce_only`), וקל להרחיב את הפרסינג של `note` כדי להזריק אותם לביצוע.

**ניהול פוזיציה מהיר (ללא סריקות רקע)** — מומלץ להוסיף endpoints:
- `/ops/close_half` — סגירת 50% כמות MARKET (reduceOnly).
- `/ops/close_all` — סגירת 100% כמות MARKET (reduceOnly).
- `/ops/reverse` — סגירה מלאה + פתיחה בצד ההפוך באותה כמות.

---

## 🛠️ התקנה והפעלה מקומית
```bash
git clone https://github.com/your-org/algogpt.git
cd algogpt
python -m venv .venv
source .venv/bin/activate  # ב-Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 10000





























