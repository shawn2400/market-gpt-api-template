# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

מערכת Algo אוטומטית לניתוח טכני, חישובי SL/TP, ניהול טריידים, Grid חכם, ניתוח חדשות, הפקת דוחות PDF, וביצוע מסחר חי ב-Binance.
פועלת לפי כללים קשיחים בזמן אמת, רצה על Render עם REST API תקני.

## תכונות עיקריות

- ✅ ניתוח טכני חי (RSI, MACD, EMA, BB, ADX, ATR, OBV)
- ✅ חישוב SL/TP כולל תמיכה ב-ATR
- ✅ ניתוח Multi-TF (15m / 1h)
- ✅ Backtest מובנה
- ✅ Dry-run / Live (בהתאם לדגלים)
- ✅ סטטיסטיקות PNL + יצוא PDF
- ✅ OpenAPI מלא + Dashboard HTML בסיסי

## הפעלה

```bash
export API_BEARER_TOKEN="your_token"
# אופציונלי: מפתחות Binance ו/או OpenAI
export BINANCE_API_KEY="..."
export BINANCE_API_SECRET="..."
export OPENAI_API_KEY="..."

uvicorn main:app --host 0.0.0.0 --port 10000





