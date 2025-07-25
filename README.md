# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

מערכת אוטומטית לניתוח טכני, חישובי SL/TP, ניהול טריידים, רטרוספקטיבה, וסינון איכות מבוסס Confidence.

---

## 🚀 תכונות עיקריות

- ✅ ניתוח טכני בזמן אמת (RSI, MACD, ATR)
- ✅ חישובי SL/TP מדויקים כולל Trailing SL
- ✅ שמירת טריידים לפי חוקים קשיחים: Confidence, RRR, מינוף
- ✅ תמיכה ב־Limit ו־Stop-Limit Orders
- ✅ תמיכה ב־Regular ו־Grid Trades
- ✅ ניהול מצב פתוח/סגור של טריידים
- ✅ Backtest אוטומטי עם סינון איכות
- ✅ תמיכה ב־Auto Risk Allocation לפי היסטוריית טריידים
- ✅ תמיכה ב־Trailing TP/SL חכם
- ✅ ניתוח ב־2 טיימפריימים: 15m ו־1h
- ✅ הצגת גרפים בזמן אמת כ־base64 (תמיכה מלאה ב־GPT)

---

## 🧠 תוספות מתקדמות (Pro Elite)

- 📌 Confidence גמיש מ־88%+
- 📌 מינוף גמיש 5×–35×
- 📌 חישוב RRR דינמי לפי ATR
- 📌 סינון לפי סוג טרייד: Regular / Grid
- 📌 שמירת איכות (Quality Score)
- 📌 פיצול תקציב ל־2 טריידים אם תנאים מתאימים
- 📌 שילוב קורלציות מטבעות
- 📌 שילוב Order Blocks ו־FVG
- 📌 תמיכה באוטומציה עתידית (חיבור לבורסות/בוטים)

---

## 📡 מסלולים

| נתיב | תיאור |
|------|--------|
| `/price` | קבלת מחיר של מטבע |
| `/calculate-sl-tp` | חישוב SL / TP כולל RRR |
| `/calculate-quantity` | חישוב כמות לפי תקציב ומינוף |
| `/save-trade` | שמירת טרייד (בכפוף לכללים) |
| `/get-trades` | הצגת כל הטריידים |
| `/clear-trades` | מחיקת כל הטריידים |
| `/active-trade` | בדיקה אם יש טרייד פתוח |
| `/update-trade` | עדכון סטטוס טרייד ל־CLOSED |
| `/backtest` | בדיקה רטרוספקטיבית לנתונים |
| `/analyze` | ניתוח טכני ל־15m ו־1h |

---

## 🛠 התקנה מקומית

```bash
git clone https://github.com/your-username/AlgoGPT.git
cd AlgoGPT
pip install -r requirements.txt
python main.py



