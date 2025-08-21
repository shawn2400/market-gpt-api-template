# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת (Binance Futures / Spot / Grid)

**AlgoGPT** היא מערכת מסחר אלגוריתמית חיה מבוססת **FastAPI** שמתחברת ל־**Binance** ומבצעת:

- 📈 **ניתוח טכני חכם**: RSI, MACD, EMA21/50, ATR, FVG, Volume Spike  
- 🎯 **חישובי SL/TP חכמים**: סטטי, Trailing, ATR × 1.5  
- 🔎 **סריקות בזמן אמת** לפי טרנד, נפח ו־Multi-TF (15m + 1h)  
- 🧪 **Backtest** לאסטרטגיות היסטוריות  
- 🤖 **אינטגרציה עם OpenAI (GPT-4o)** לניתוחים איכותיים (Quality Scoring)  
- 📊 **דוחות ודשבורד**: PnL, סטטיסטיקות, גרפים ו־PDF  

---

## 🚀 התקנה מקומית (Local Dev)

```bash
# 1. הורדת הקוד
git clone https://github.com/your-org/algogpt.git
cd algogpt

# 2. יצירת סביבה וירטואלית
python -m venv .venv
source .venv/bin/activate   # ב-Windows: .venv\Scripts\activate

# 3. התקנת תלויות
pip install --upgrade pip
pip install -r requirements.txt

# 4. הפעלת השרת (development mode)
uvicorn main:app --reload --port 10000













