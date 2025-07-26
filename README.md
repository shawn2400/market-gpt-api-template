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

## 📡 API — מסלולים נתמכים

| נתיב API              | תיאור                                              |
|-----------------------|-----------------------------------------------------|
| `/price`              | קבלת מחיר עדכני למטבע                             |
| `/calculate-sl-tp`    | חישוב SL/TP כולל יחס RRR                          |
| `/calculate-quantity` | חישוב כמות לפי תקציב, מינוף ומחיר כניסה          |
| `/save-trade`         | שמירת טרייד חדש למעקב                             |
| `/save-and-execute`   | שמירה + שליחה אוטומטית לביצוע ב־Binance          |
| `/get-trades`         | הצגת כל הטריידים השמורים                          |
| `/clear-trades`       | מחיקת כל הטריידים                                 |
| `/active-trade`       | בדיקת טריידים פתוחים                              |
| `/update-trade`       | סגירת טרייד לפי סימול                              |
| `/backtest`           | בדיקת אסטרטגיה על סמך היסטוריה                   |
| `/analyze`            | ניתוח טכני בזמן אמת                               |
| `/execute-trade`      | שליחה למסחר בפועל (Spot / Futures)               |
| `/current-time-il`    | השעה הנוכחית בישראל + האם "שעה חמה"              |
| `/stats`              | סטטיסטיקות PNL כלליות + Win Rate                 |
| `/snapshot`           | הפקת תמונה גרפית לטרייד (Base64 Chart)           |
| `/news`               | קבלת חדשות חשובות מ־CryptoPanic                  |
| `/daily-report`       | הפקת דוח PDF יומי כולל גרף וסטטיסטיקות           |
| `/email-alert`        | שליחת התראה פנימית במייל ללא שירות חיצוני        |

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





