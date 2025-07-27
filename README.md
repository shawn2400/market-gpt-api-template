# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

מערכת Algo אוטומטית לניתוח טכני, חישובי SL/TP, ניהול טריידים, Grid חכם, ניתוח חדשות, הפקת דוחות PDF, וביצוע מסחר חי ב־Binance.  
פועלת לפי כללים קשיחים בזמן אמת, רצה על Render עם REST API תקני.

---

## 🚀 תכונות עיקריות

- ✅ ניתוח טכני חי (RSI, MACD, EMA, BB, ADX, ATR, OBV)
- ✅ חישוב SL ו־TP כולל Trailing SL ודינמיקה לפי תנודתיות
- ✅ חישוב SL לפי ATR × 1.5 בלבד
- ✅ ניתוח בטיימפריימים כפולים: 15m ו־1h בלבד
- ✅ תמיכה בהזמנות Limit / Stop-Limit בלבד
- ✅ ניהול עד 4 טריידים פתוחים במקביל
- ✅ תמיכה מלאה ב־Spot, Futures ו־Grid
- ✅ Smart Grid לפי Confidence
- ✅ תצוגת גרף Base64 (ל־GPT / Dashboard)
- ✅ ניתוח Order Blocks ו־Fair Value Gaps (FVG)
- ✅ Backtest כולל quality_score
- ✅ חיבור Binance API (כולל שליחת עסקאות)
- ✅ סטטיסטיקות PNL, Win Rate, רווח יומי / חודשי

---

## 🧠 הרחבות Pro Elite

- 📌 Confidence גמיש (88%+ או 86% עם quality_score ≥ 4)
- 📌 מינוף אוטומטי לפי רווחיות ו־SL (5× עד 35×)
- 📌 Trailing SL/TP לפי תנודתיות
- 📌 פיצול תקציב ל־2 טריידים רק אם אין קורלציה
- 📌 Filtering לפי איכות אינדיקטורים ו־Scoring
- 📌 כניסה רק לפי Breakout / Pullback / Reversal
- 📌 Auto Risk Allocation
- 📌 ניתוח עומק כולל נרות, קורלציות, נזילות, Volume Spike
- 📌 תמיכה ב־PNL Tracker
- 📌 Snapshot גרפי לכל טרייד

---

## 🗞️ חדשות ודוחות

- 📰 ניתוח חדשות מ־CryptoPanic API (סנטימנט חיובי / שלילי)
- 📊 דוחות PDF יומיים אוטומטיים:
  - גרף PNL יומי
  - סיכום רווחים
  - Win Rate
  - רווח יומי נוכחי

---

## 📡 REST API — מסלולים נתמכים

| נתיב API              | תיאור                                              |
|-----------------------|-----------------------------------------------------|
| `/`                   | בדיקת תקינות ה־API                                 |
| `/sl_tp`              | חישוב SL/TP כולל יחס RRR                          |
| `/calculate-quantity` | חישוב כמות לפי תקציב, מינוף ומחיר כניסה          |
| `/save`               | שמירת טרייד חדש למעקב                             |
| `/trades`             | הצגת כל הטריידים השמורים                          |
| `/clear`              | מחיקת כל הטריידים                                 |
| `/open-trades`        | הצגת טריידים פתוחים                               |
| `/close-trade`        | סגירת טרייד לפי סימול                             |
| `/backtest`           | בדיקת אסטרטגיה על סמך היסטוריה                   |
| `/scan`               | סריקה טכנית חיה של Binance Futures               |
| `/execute-trade`      | שליחה למסחר בפועל (Spot / Futures)               |
| `/daily-report`       | הפקת דוח PDF יומי כולל גרף וסטטיסטיקות           |
| `/ai-analyze`         | חיזוי AI גרפי לתחום מחירים                       |
| `/stats`              | סטטיסטיקות רווחים ו־Win Rate                      |
| `/preset`             | שליפת קובץ הגדרות                                 |
| `/strategy`           | הצגת כללי אסטרטגיה                                |
| `/news`               | קבלת חדשות מ־CryptoPanic                          |

---

## 🔐 קובץ .env (חובה)

```env
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
CRYPTO_PANIC_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## 🧪 דוגמה לשליחת טרייד חדש (POST /save)

```bash
curl -X POST http://localhost:10000/save \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "entry": 30000,
    "stop": 29000,
    "tp": 33000,
    "leverage": 10,
    "direction": "LONG",
    "confidence": 91,
    "type": "REGULAR"
  }'
```

---

## 💰 תקציב

- ברירת מחדל: **$100–$1000**
- כל טרייד מקבל תקציב דינמי לפי SL, מינוף, נזילות ו־confidence
- תמיכה בפיצול תקציב (רק אם אין קורלציה בין טריידים)

---

## 🛠️ התקנה מקומית

```bash
git clone https://github.com/your-username/AlgoGPT.git
cd AlgoGPT
pip install -r requirements.txt
python main.py
```

---

✅ נבדק מול הקוד הראשי (`main.py`, `openapi.yaml`) — כל הנתיבים תקינים.
עודכן בתאריך: 2025-07-27






