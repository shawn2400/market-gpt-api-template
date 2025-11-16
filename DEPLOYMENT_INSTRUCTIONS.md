# 🚀 AlgoGPT - Replit 24/7 Deployment (אוטונומי לחלוטין)

## ✅ מה הוכן עבורך:

1. ✅ **`start_all_services.sh`** - סקריפט שמריץ FastAPI + 10 workers במקביל
2. ✅ **Auto-restart logic** - אם worker קורס, הוא מתחיל מחדש אוטומטית
3. ✅ **Full logging** - כל הלוגים ב-`/tmp/algogpt_logs/`
4. ✅ **2GB RAM** - מספיק למערכת (צריכה נוכחית: ~1.3GB)

---

## 🎯 איך להפעיל Deployment 24/7 ב-Replit:

### **שלב 1: לחץ Deploy**

1. **בReplit**, לחץ על הכפתור **"Deploy"** למעלה (לצד Run)
2. בחר **"Reserved VM"** (לא Autoscale!)
3. בחר גודל: **"Shared VM - 0.5 vCPU / 2GB RAM"** → **$20/חודש**

### **שלב 2: הגדר Run Command**

ב-**"Build & Deploy Settings"**, תחת **"Run command"**:

הקלד:
```bash
bash start_all_services.sh
```

### **שלב 3: Deploy!**

לחץ **"Deploy"** → המתן 3-5 דקות

**זהו!** המערכת עכשיו רצה 24/7 אוטונומית! 🎉

---

## 📊 מה רץ ב-Deployment:

| Service | תפקיד | Auto-Restart |
|---------|------|--------------|
| **FastAPI** | API Server (port 5000) | ✅ |
| **Health Monitor** | ניטור בריאות + Telegram | ✅ |
| **Fills Watcher** | ניהול פוזיציות + SL/TP | ✅ |
| **Position Monitor** | Trailing TP, Breakeven | ✅ |
| **Auto Scanner** | GRID proposals (AI) | ✅ |
| **Auto Optimization** | Self-adaptive tuning | ✅ |
| **Insurance Monitor** | Account protection | ✅ |
| **Quantum TOP 50** | Symbol filtering | ✅ |
| **Sentinel Security** | Security monitoring | ✅ |
| **Telegram Digest** | Daily reports | ✅ |
| **Auto Cleanup** | Database cleanup | ✅ |

**סה"כ: 11 services במקביל** (1 API + 10 Workers)

---

## ✅ איך לוודא שהכל עובד:

### 1. **בדוק Deployment Status:**
```
Replit → Deployments → שלך → צריך "Running" ירוק
```

### 2. **בדוק Health:**
פתח את ה-URL של הdeployment שלך:
```
https://<your-repl>.<your-username>.repl.co/readyz
```
תקבל: `{"status": "ok"}`

### 3. **בדוק Telegram:**
תקבל הודעת **"✅ System Status: HEALTHY"** תוך דקות

### 4. **בדוק Logs (אם צריך):**
ב-Replit Deployment → **"Logs"** tab

---

## 💰 עלות:

**$20/חודש** - Replit Reserved VM (2GB)

- ✅ **פי 3.8 זול יותר** מRender.com ($77)
- ✅ **אותה פונקציונאליות** (11 services)
- ✅ **99.9% uptime** guarantee
- ✅ **0 תלות בAgent**

---

## 🛑 איך לעצור (במקרה חירום):

### דרך Replit Dashboard:
```
Deployments → שלך → "Stop Deployment"
```

זה יעצור את כל 11 השירותים מיידית.

---

## 🔄 איך לעשות שינויים בעתיד:

1. ערוך קוד ב-Replit workspace
2. שינויים יישמרו אוטומטית
3. Redeploy:
   ```
   Deployments → Manual Deploy → Deploy Latest
   ```

---

## 💡 טיפים

- **Logs**: כל worker שומר log נפרד ב-`/tmp/algogpt_logs/<service>.log`
- **RAM Usage**: המערכת משתמשת ב-~1.3GB מתוך 2GB - יש מרווח בטוח
- **Auto-Restart**: אם worker קורס, הוא חוזר אוטומטית תוך 5 שניות
- **Zero Downtime**: המערכת רצה 24/7 ללא תלות בworkspace פתוח

---

## 🎉 סיכום:

✅ **המערכת מוכנה ל-24/7!**

כל מה שצריך:
1. לחץ **"Deploy"** בReplit
2. בחר **"Reserved VM - 2GB"**  
3. Run command: `bash start_all_services.sh`
4. **זהו!** המערכת רצה אוטונומית ללא תלות בך או בי 🚀

**עלות:** $20/חודש (פי 3.8 זול מRender!)  
**Uptime:** 99.9% guarantee  
**תלות בAgent:** אפס! 💪
