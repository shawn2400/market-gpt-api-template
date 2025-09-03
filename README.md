# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת (Binance Futures / Spot / Grid)

**AlgoGPT** היא מערכת מסחר אלגוריתמית מבוססת **FastAPI** עם אינטגרציה ל־**Binance**, ניתוח טכני רב־שכבתי, ניהול חי דטרמיניסטי (SL/TP/Breakeven/Trailing), ו**סוכן GPT** קשוח, קר, ומוכוון-מטרה לקבלת החלטות Trade/No-Trade.

## תמצית יכולות
- 📈 **ניתוח טכני**: RSI, MACD, EMA21/50, ATR, BB, OBV, FVG, Volume Spike
- 🧭 **SOP קשיח**: BTC-Gate, TF Align (5m/15m/1h), Spread/Depth/Funding/Δ%5m, Volume≥1.2×MA20
- 🎯 **SL/TP חכמים**: סטטי, Breakeven fee-aware, Trailing ATR (hysteresis)
- 🤖 **Agent GPT**: איכות קרה, פלט JSON לפי `OUTPUT_SCHEMA.json`, סיבת פסילה (`reason_code`)
- 🧪 **Backtest & Shadow**: Walk-Forward מקומי, Shadow-mode למדידת Edge
- 📊 **דוחות & מדדים**: `/metrics` כולל p50/p95, avg_time_to_BE, stalls_resolved
- 🛡️ **היגיינת Orders**: Limit Post-Only, Stop-Limit (Trigger=MARK), Reduce-Only, Idempotency

---

## 🚀 התקנה מקומית (Local Dev)

```bash
git clone https://github.com/your-org/algogpt.git
cd algogpt
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --reload --port 10000














