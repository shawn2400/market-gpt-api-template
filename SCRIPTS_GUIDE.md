# 🛠️ AlgoGPT Scripts Guide (Replit Edition)

## ✅ All Fixed for Replit!
All scripts have been adapted from Render (`/app`) to Replit (`/home/runner/workspace`).
**No more `/app/menu.sh` errors!**

---

## Quick Commands

### 1. Main Menu (Interactive) ⭐ RECOMMENDED
```bash
bash menu.sh
# או
bash scripts/menu.sh
```

### 2. Quick System Check
```bash
bash scripts/check_system.sh
```

### 3. Check Binance Connection
```bash
bash scripts/check_binance_api.sh
```

---

## Menu Options

| אופציה | תיאור | פעולה |
|--------|--------|--------|
| **1** | 📦 בדיקת מצב | בודק אם השרת רץ ועונה |
| **2** | 🔁 ריסטרט | הוראות לריסטרט workflows |
| **3** | 🧠 AI Scanner | ריסטרט Auto Scanner בלבד |
| **4** | 🧩 משתני סביבה | בדיקת secrets (מוסתרים חלקית) |
| **5** | 🚀 Auto Scanner | בדיקת לוגים של Scanner |
| **6** | 🔍 Binance | בדיקת חיבור ל-Binance API |
| **7** | 🧱 מערכת מלאה | בדיקה מקיפה (processes, logs, health, CPU, Memory) |
| **8** | ❌ יציאה | סגירת התפריט |

---

## System Health Check Output

```
🔍 AlgoGPT System Health Check
================================

1️⃣ Server Status:
{"status":"healthy"} ✅

2️⃣ Workflows:
   Running processes: 5

3️⃣ Dynamic Filters:
   Market Mood: 🟢 Aggressive (שוק חזק)

4️⃣ Binance API:
   ✅ Connected

5️⃣ Environment:
   ✅ BINANCE_API_KEY
   ✅ OPENAI_API_KEY
   ✅ TELEGRAM_BOT_TOKEN
   ✅ TELEGRAM_CHAT_ID: 449087907
```

---

## Useful Commands

### View Logs
```bash
# Server logs
tail -f /tmp/logs/AlgoGPT_Server_*.log

# Auto Scanner logs
tail -f /tmp/logs/Auto_Scanner_*.log

# All logs
ls -lth /tmp/logs/
```

### Check Workflows
```bash
ps aux | grep gunicorn
ps aux | grep gpt_auto_suggest
```

### Test API Endpoints
```bash
# Health check
curl http://localhost:5000/health

# Full status
curl http://localhost:5000/ | python3 -m json.tool

# Binance test
curl https://fapi.binance.com/fapi/v1/time
```

---

## 🚀 Quick Start After Repl Restart

```bash
# 1. Check everything is running
bash menu.sh
# Choose option 1

# 2. Verify Binance connection
bash menu.sh
# Choose option 6

# 3. Check Auto Scanner
tail -20 /tmp/logs/Auto_Scanner_*.log
```

---

## 🔧 What Was Fixed

### Before (Render):
```bash
cd /app || exit 1                    # ❌ Fails on Replit
LOG_FILE="/app/logs/auto_intel.log"  # ❌ /app doesn't exist
```

### After (Replit):
```bash
cd "$PROJECT_ROOT" || exit 1         # ✅ Works on Replit
LOG_FILE="/tmp/logs/auto_intel.log"  # ✅ Uses /tmp/logs
```

### Files Fixed:
- ✅ `scripts/menu.sh` - Completely rewritten (206 → 127 lines)
- ✅ `menu.sh` - Shortcut in project root
- ✅ `scripts/auto_intel_daemon.sh` - `/app/logs` → `/tmp/logs`
- ✅ `scripts/check_system.sh` - New quick health check

---

## 📝 Notes

- All scripts adapted for **Replit environment** (`/home/runner/workspace`)
- Workflows managed by **Replit Workflows UI**
- No Docker/Supervisor needed - pure Replit setup
- Dynamic Filters auto-adjust every 60 seconds
- Telegram approval workflow ready 24/7

**✅ System is fully automated and self-managing!**

---

## 💡 Tips

1. **Use option 7** for comprehensive system check (shows CPU, Memory, Processes, Logs)
2. **Use option 4** to verify all secrets are loaded
3. **Use option 6** to test Binance API connection
4. Logs are stored in `/tmp/logs/` (auto-managed by Replit)
5. All timestamps in logs show Israel time (🕐 שעון ישראל)

---

## 🎯 Common Tasks

### Check if everything is running:
```bash
bash menu.sh <<< "7"
```

### Check Binance connection:
```bash
bash menu.sh <<< "6"
```

### Check secrets:
```bash
bash menu.sh <<< "4"
```

### View latest Scanner logs:
```bash
bash menu.sh <<< "5"
```

---

**🚀 AlgoGPT - Fully Operational on Replit!**
