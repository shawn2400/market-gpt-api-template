# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

מערכת Algo אוטומטית לניתוח טכני, חישובי SL/TP, ניהול טריידים, גריד חכם, Backtest ומסחר ישיר ב־Binance Futures או Spot.  
פועלת בזמן אמת לפי כללים קשיחים ו־API חי על שרת Render.

---

## 🚀 תכונות עיקריות

- ✅ ניתוח טכני חי (RSI, MACD, EMA, BB, ADX, ATR, OBV)
- ✅ חישוב SL ו־TP כולל Trailing SL ודינמיקה לפי תנודתיות
- ✅ חישוב SL לפי ATR × 1.5 בלבד
- ✅ ניתוח בטיימפריימים כפולים: 15m ו־1h בלבד
- ✅ תמיכה בהזמנות Limit / Stop-Limit בלבד
- ✅ ניהול טרייד יחיד (ACTIVE בלבד)
- ✅ תמיכה מלאה ב־Spot, Futures ו־Grid
- ✅ Smart Grid לפי Confidence
- ✅ תצוגת גרף (base64) ל־GPT
- ✅ ניתוח Order Blocks ו־Fair Value Gaps (FVG)
- ✅ Backtest כולל quality_score
- ✅ תמיכה מלאה ב־Binance API LIVE (כולל ביצוע פקודות)

---

## 🧠 הרחבות Pro Elite

- 📌 Confidence גמיש (88%+ או 86% עם quality_score ≥ 4)
- 📌 מינוף אוטומטי לפי רווחיות ו־SL (5× עד 35×)
- 📌 Trailing SL/TP לפי תנודתיות
- 📌 פיצול תקציב ל־2 טריידים רק אם אין קורלציה
- 📌 Filtering לפי איכות אינדיקטורים ו־Scoring
- 📌 כניסה רק לפי Breakout / Pullback / Reversal
- 📌 Auto Risk Allocation
- 📌 ניתוח עומק מלא כולל נרות, קורלציות, נפח חריג

---

## 🔧 תכונות עתידיות (בפיתוח)

- 🤖 Machine Learning לזיהוי טריידים חוזרים
- 📈 Heatmaps לזיהוי עומק שוק
- 🧠 Liquidity Zones
- 📘 יומן טריידים חכם
- 📊 ניתוח תיק השקעות

---

## 📡 API — מסלולים נתמכים

| נתיב API              | תיאור                                              |
|-----------------------|-----------------------------------------------------|
| `/price`              | קבלת מחיר למטבע מסוים                             |
| `/calculate-sl-tp`    | חישוב SL/TP כולל RRR                              |
| `/calculate-quantity` | חישוב כמות לפי תקציב, מינוף ומחיר                 |
| `/save-trade`         | שמירת טרייד חדש (כולל סטטוס, סיבה, אינדיקטורים)  |
| `/get-trades`         | קבלת כל הטריידים                                   |
| `/clear-trades`       | מחיקת טריידים קיימים                               |
| `/active-trade`       | בדיקת טרייד פתוח                                  |
| `/update-trade`       | סגירת טרייד לפי סימול                              |
| `/backtest`           | בדיקת אסטרטגיה לאחור                              |
| `/analyze`            | ניתוח טכני בזמן אמת                               |
| `/execute-trade`      | ביצוע טרייד בפועל (Spot / Futures)                |
| `/current-time-il`    | הצגת שעה נוכחית בישראל + בדיקת "שעה חמה"         |

---

## 💰 תקציב

- ברירת מחדל: **$100–$1000**
- כל טרייד מקבל תקציב מותאם לפי Confidence, SL, מינוף ונזילות
- תמיכה בפיצול תקציב רק אם אין קורלציה בין טריידים

---

## ⚙️ התקנה מקומית

```bash
git clone https://github.com/your-username/AlgoGPT.git
cd AlgoGPT
pip install -r requirements.txt
python main.py




