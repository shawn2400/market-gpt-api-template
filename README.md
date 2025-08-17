# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

API למסחר אלגוריתמי ב-Binance (Futures/Spot/Grid), סריקות Multi-TF עם אינדיקטורים, חישובי SL/TP, Backtest ודשבורד HTML קליל.  
נבנה ב-FastAPI ומוכן לפריסה ב-Docker/Render.

---

## 🚀 התחלה מהירה

### A) הרצה מקומית (Python)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
export PORT=10000
uvicorn main:app --host 0.0.0.0 --port ${PORT}






