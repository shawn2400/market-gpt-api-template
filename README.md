# README.md

# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

מערכת Algo אוטומטית לניתוח טכני, חישובי SL/TP, ניהול טריידים, Grid חכם, ניתוח חדשות, הפקת דוחות PDF, וביצוע מסחר חי ב״Binance.
פועלת לפי כללים קשיחים בזמן אמת, רצה על Render עם REST API תקני.

## תכונות עיקריות

* ✅ ניתוח טכני חי (RSI, MACD, EMA, BB, ADX, ATR, OBV)
* ✅ חישוב SL ו׼tp כולל Trailing SL ודינמיקה לפי תנועותיות
* ✅ חישוב SL לפי ATR × 1.5 בלבד
* ✅ ניתוח בטיימפריימים כפולים: 15m ו״1h
* ✅ תמיכה בהזמנות Limit / Stop-Limit בלבד
* ✅ ניהול עד 4 טריידים פתוחים במקביל
* ✅ תמיכה מלאה ב״Spot, Futures ו״Grid
* ✅ Smart Grid לפי Confidence
* ✅ תצוגת גרף Base64 (ל״GPT / Dashboard)
* ✅ ניתוח Order Blocks ו״Fair Value Gaps (FVG)
* ✅ Backtest כולל quality\_score
* ✅ חיבור Binance API (כולל שליחת עסקאות)
* ✅ סטטיסטיקות PNL, Win Rate, רווח יומי / חודשי

## REST API — נתיבים נתמכים

| נתיב API              | תיאור                       |
| --------------------- | --------------------------- |
| `/`                   | בדיקת תקינות השרת           |
| `/scan`               | סריקה חיה Futures / Spot    |
| `/scan/multi`         | סריקה Multi-TF + AI         |
| `/execute-trade`      | ביצוע טרייד חי בפועל        |
| `/grid/trade`         | פעולה גריד חי עם Binance    |
| `/grid/status`        | סטטוס הגריד האחרון          |
| `/calculate-quantity` | חישוב כמות לפי תקציב ומינוף |
| `/sl_tp`              | חישוב SL/TP חכם             |
| `/backtest`           | סימולציה אסטרטגיה           |
| `/ai-analyze`         | חיזוי AI לטחום מחירים       |
| `/daily-report`       | דוח PDF יומי אוטומטי        |
| `/news`               | קבלת חדשות מעודכנות         |

---

# openapi.yaml

כפי הדרכן נדון, ה־`openapi.yaml` מכיל:

* תיעוד מלא לגרידים (`/grid/trade`, `/grid/status`)
* תמיכה בבחירת שוק: Spot / Futures / Grid (שדה `market`)
* הגדרות למסלולים: SL/TP, Backtest, Quantity, ניתוח AI, חדשות
* תמיכה ב־Auto Executor (`/executor/start`, `/executor/stop`, `/executor/status`)
* שימוש בפרמטרים כמו trending\_only, trending\_source, top, וכו'

הגרסה `2.0.2` מעודכנת, שלמה, ומסונכרנת מול הקוד הראשי.

---

🚀 הכל מוכנן לפעלה בשרת Render או בהרצה מקומית!






