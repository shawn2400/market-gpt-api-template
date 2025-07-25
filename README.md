# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

מערכת אוטומטית לניתוח טכני, חישובי SL/TP, ניהול טריידים, סריקת הזדמנויות, Backtest, גריד חכם ומסחר ישיר ב־Binance Futures (כולל תמיכה ב־Grid ו־Spot).

---

## 🚀 תכונות עיקריות

- ✅ ניתוח טכני בזמן אמת: RSI, MACD, EMA, BB, ATR
- ✅ חישוב SL/TP כולל Trailing SL ו־RRR דינמי
- ✅ תמיכה ב־SL לפי ATR × 1.5 בלבד
- ✅ ניתוח לפי שני טיימפריימים: 15m ו־1h
- ✅ תמיכה ב־LIMIT ו־STOP-LIMIT בלבד
- ✅ ניהול טריידים עם סטטוס (ACTIVE / CLOSED)
- ✅ הצגת גרף כ־Base64 לצרכי GPT
- ✅ תמיכה ב־Regular ו־Grid trades
- ✅ תמיכה מלאה ב־Active Trade יחיד בלבד
- ✅ Smart Grid אוטומטי לפי Confidence
- ✅ זיהוי אוטומטי של FVG ו־Order Blocks
- ✅ Backtest כולל quality_score
- ✅ תמיכה מלאה במסחר חי (LIVE) דרך Binance API
- ✅ שליחה אוטומטית של טריידים ל־Binance כולל spot ו־futures

---

## 🧠 הרחבות Pro Elite

- 📌 Confidence גמיש (88%+ או 86% עם תנאים)
- 📌 מינוף דינמי בין 5× ל־35× לפי איכות טרייד
- 📌 Order Type חכם (Limit / Stop-Limit בלבד)
- 📌 Trailing SL ו־TP אוטומטיים לפי תנודתיות
- 📌 תמיכה בפיצול תקציב ל־2 טריידים אם אין קורלציה
- 📌 Filtering לפי איכות אינדיקטורים ו־quality_score
- 📌 ניתוח קורלציה בין מטבעות – מניעת טריידים חופפים
- 📌 כניסה רק לפי Breakout / Pullback / Reversal אמיתי
- 📌 Auto Risk Allocation לפי טריידים היסטוריים
- 📌 ניתוח גרפי כולל תצפיות נריות

---

## 🔧 פיצ’רים לעתיד (בפיתוח)

- 🧠 ניתוח Machine Learning (תשתית מוכנה)
- 📈 Heatmaps לפי עומק שוק
- 💧 Liquidity Zones לזיהוי אזורי נזילות מוסדיים
- 💼 ניהול תיק השקעות
- 📘 יומן טריידים חכם (כולל הערות, קטגוריות, הצלחות)

---

## 📡 מסלולי API

| נתיב                  | תיאור                                              |
|-----------------------|-----------------------------------------------------|
| `/price`              | קבלת מחיר עדכני ממקור Binance API                  |
| `/calculate-sl-tp`    | חישוב SL / TP כולל יחס סיכון־רווח (RRR)            |
| `/calculate-quantity` | חישוב כמות בהתאם לתקציב ומינוף                     |
| `/save-trade`         | שמירת טרייד חדש אם עומד בכללים                      |
| `/get-trades`         | הצגת כל הטריידים השמורים                            |
| `/clear-trades`       | מחיקת כל הטריידים                                   |
| `/active-trade`       | בדיקה אם יש טרייד פתוח                              |
| `/update-trade`       | עדכון סטטוס טרייד קיים ל־CLOSED                    |
| `/backtest`           | ניתוח אסטרטגי לאחור כולל אינדיקטורים              |
| `/analyze`            | ניתוח טכני בזמן אמת כולל ניתוח עומק               |
| `/execute-trade`      | ביצוע טרייד בפועל ב־Binance Futures או Spot        |

---

## 🛠 התקנה מקומית

```bash
git clone https://github.com/your-username/AlgoGPT.git
cd AlgoGPT
pip install -r requirements.txt
python main.py



