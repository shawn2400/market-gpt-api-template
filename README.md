# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת (Binance Futures / Spot / Grid)

**AlgoGPT** היא מערכת מסחר אלגוריתמית מבוססת **FastAPI** עם אינטגרציה ל־**Binance**, ניתוח טכני רב־שכבתי, ניהול חי דטרמיניסטי (SL/TP/Breakeven/Trailing), ו**סוכן GPT** קשוח ומוכוון-מטרה.

---

## 🚀 יכולות
- 📈 **ניתוח טכני**: RSI, MACD, EMA21/50, ATR, BB, OBV, FVG
- 🧭 **SOP קשיח**: BTC-Gate, TF Align (5m/15m/1h), Spread/Depth/Funding
- 🎯 **ניהול חי**: SL/TP, Breakeven, Trailing ATR
- 🤖 **Agent GPT**: ניתוח AI, פלט JSON, `reason_code`
- 📊 **דוחות**: Auto Summary אחרי כל טרייד, Daily/Weekly/Monthly בטלגרם
- 🛡️ **היגיינת Orders**: Limit Post-Only, Stop-Limit, Reduce-Only

---

## 📦 התקנה מקומית
```bash
git clone https://github.com/your-org/algogpt.git
cd algogpt
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 10000














