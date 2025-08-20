# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת (Binance Futures / Spot / Grid)

AlgoGPT היא מערכת מסחר אלגוריתמית חיה מבוססת FastAPI שמתחברת ל־Binance ומבצעת:
- ניתוח טכני חכם (RSI, MACD, EMA, FVG)
- חישובי SL/TP ודינמיקת ATR
- סריקות לפי טרנד ונפח
- Backtest לאסטרטגיות
- אינטגרציה עם OpenAI (GPT-4o)
- הפקת דוחות, סטטיסטיקות ודשבורד

---

## 🚀 התקנה מקומית

```bash
git clone https://github.com/your-org/algogpt.git
cd algogpt

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

uvicorn main:app --reload --port 10000










