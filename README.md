# 📊 AlgoGPT — מערכת מסחר חכמה בזמן אמת

AlgoGPT היא מערכת מסחר בזמן אמת עבור Binance (Futures / Spot / Grid) המבצעת:
- סריקות שוק חכמות עם אינדיקטורים (RSI, MACD, BB וכו')
- חישובי SL/TP כולל Trailing
- Backtest אסטרטגיות
- הפקת דוחות AI, חיבור חדשות, סטטיסטיקות ועוד

### 🚀 REST API — נתיבים פעילים

| נתיב | תיאור |
|------|--------|
| `/` | בדיקת תקינות |
| `/metrics` | מדדי ביצועים |
| `/__routes` | כל המסלולים הפעילים |
| `/trade/execute` | ביצוע טרייד (LIVE או בדיקה) |
| `/ai/ai-analyze` | ניתוח איכות טרייד עם עוגן |
| `/backtest` | סימולציית אסטרטגיה |
| `/scan/top-volume` | סריקת סמלים לפי טרנד |
| `/scan/info` | סטטוס סורק ו־Executor |
| `/news` | חדשות שוק |
| `/grid/status` | סטטוס גריד פעיל (נדרש Token) |

---

### ⚙️ התקנה מהירה

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 10000








