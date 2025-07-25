# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

מערכת אוטומטית לניתוח טכני, חישובי SL/TP, ניהול טריידים, רטרוספקטיבה, סינון איכות מבוסס Confidence, ו־Backtest לפי כללי סוחר Algo.

---

## 🚀 תכונות עיקריות

- ✅ ניתוח טכני בזמן אמת: RSI, MACD, EMA, BB, ATR
- ✅ חישוב SL/TP כולל Trailing SL ו־RRR דינמי
- ✅ שמירת טריידים לפי חוקים קשיחים (RRR, SL, Confidence)
- ✅ תמיכה ב־LIMIT ו־STOP-LIMIT בלבד
- ✅ ניתוח על טיימפריימים 15m ו־1h
- ✅ תמיכה ב־Regular ו־Grid trades
- ✅ תמיכה ב־Active Trade יחיד בלבד
- ✅ Backtest כולל Quality Score
- ✅ הצגת גרף כ־Base64 לצרכי GPT
- ✅ זיהוי אוטומטי של FVG ו־Order Blocks
- ✅ תמיכה ב־Auto Risk Allocation לפי היסטוריית טריידים

---

## 🧠 הרחבות Pro Elite

- 📌 מינוף דינמי (5×–35×)
- 📌 Confidence גמיש (88%+ או 86% עם תנאים)
- 📌 חישוב SL לפי ATR × 1.5 בלבד
- 📌 Trailing SL ו־TP אוטומטיים לפי תנודתיות
- 📌 Smart Grid לפי ביטחון (confidence-based grid setup)
- 📌 פיצול תקציב אם אין קורלציה בין הטריידים
- 📌 Order Type מותאם לפי תרחיש (Limit / Stop-Limit)
- 📌 Filtering לפי איכות אינדיקטורים ו־quality_score
- 📌 תמיכה בקורלציה בין מטבעות למניעת טרייד כפול
- 📌 ניהול מצב פתוח/סגור לכל טרייד
- 📌 זיהוי Breakout / Pullback / Reversal בלבד לכניסה

---

## 🔧 פיצ’רים מתקדמים לעתיד (בפיתוח)

- 🧠 ניתוח Machine Learning (תשתית מוכנה)
- 📈 Heatmaps לפי עומק שוק
- 💧 סקירת Liquidity Zones
- 📘 ניהול יומן טריידים חכם
- 💼 מערכת ניהול תיק השקעות

---

## 📡 מסלולי API

| נתיב             | תיאור                                      |
|------------------|---------------------------------------------|
| `/price`         | קבלת מחיר עדכני ממקור Binance API          |
| `/calculate-sl-tp` | חישוב SL / TP כולל יחס סיכון־רווח         |
| `/calculate-quantity` | חישוב כמות בהתאם לתקציב ומינוף        |
| `/save-trade`    | שמירת טרייד חדש אם עומד בחוקים              |
| `/get-trades`    | הצגת כל הטריידים השמורים                    |
| `/clear-trades`  | מחיקת כל הטריידים                           |
| `/active-trade`  | בדיקה אם יש טרייד פתוח                      |
| `/update-trade`  | עדכון טרייד לסטטוס "סגור"                  |
| `/backtest`      | ניתוח רטרוספקטיבי עם אינדיקטורים           |
| `/analyze`       | ניתוח חי לפי שני טיימפריימים                |

---

## 🛠 התקנה מקומית

```bash
git clone https://github.com/your-username/AlgoGPT.git
cd AlgoGPT
pip install -r requirements.txt
python main.py



