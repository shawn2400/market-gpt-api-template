# ⚡ AlgoGPT - Quick Start (3 דקות)

## 🎯 המטרה: 24/7 אוטונומי על Replit

---

## 📋 3 צעדים בלבד:

### **1. לחץ "Deploy" בReplit**
   - למעלה ליד כפתור "Run" → לחץ **"Deploy"**

### **2. בחר Reserved VM**
   - **Reserved VM** (לא Autoscale!)
   - גודל: **Shared VM - 2GB RAM** ($20/חודש)
   - Run command: **`bash start_all_services.sh`**

### **3. Deploy!**
   - לחץ **"Deploy"**
   - המתן 3-5 דקות
   
---

## ✅ זהו! המערכת רצה 24/7

### מה קורה בbackground:
- ✅ **FastAPI** רץ על port 5000
- ✅ **10 Workers** רצים במקביל:
  - Health Monitor
  - Fills Watcher (SL/TP)
  - Position Monitor (Trailing TP)
  - Auto Scanner (GRID AI)
  - Auto Optimization
  - Insurance Monitor
  - Quantum TOP 50
  - Sentinel Security
  - Telegram Digest
  - Auto Cleanup

### תקבל Telegram:
```
✅ System Status: HEALTHY
```

---

## 🔍 איך לבדוק:

**Health Check:**
```
https://<your-repl>.<username>.repl.co/readyz
```
→ `{"status": "ok"}`

**Logs:**
```
Replit → Deployments → Logs tab
```

---

## 💰 עלות:

**$20/חודש** (2GB RAM)

לעומת:
- ❌ Render.com: $77/חודש
- ❌ VPS: $32-43/חודש + ניהול

---

## 🛑 לעצור:

```
Replit → Deployments → Stop Deployment
```

---

## 🎉 זהו!

**לפרטים מלאים:** ראה `DEPLOYMENT_INSTRUCTIONS.md`

**המערכת רצה 24/7 ללא תלות בך או בAgent!** 🚀
