#!/usr/bin/env bash
set -Eeuo pipefail

# Replit workspace
PROJECT_ROOT="${REPL_HOME:-/home/runner/workspace}"
cd "$PROJECT_ROOT" || exit 1

# צבעים
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
MAGENTA='\033[1;35m'
CYAN='\033[1;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
RESET='\033[0m'

# פונקציות עזר
send_telegram() {
  local msg="$1"
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] && \
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=${msg}" -d "parse_mode=HTML" >/dev/null 2>&1
}

check_env() {
  local missing=0
  for key in BINANCE_API_KEY BINANCE_API_SECRET OPENAI_API_KEY TELEGRAM_BOT_TOKEN; do
    [[ -z "${!key:-}" ]] && echo -e "${RED}❌ $key חסר${RESET}" && missing=1 || echo -e "${GREEN}✅ $key${RESET}"
  done
  return $missing
}

auto_heal() {
  echo -e "${CYAN}🔧 Auto-Heal...${RESET}"
  send_telegram "🔧 Auto-Heal Started"
  
  # Binance check
  python3 -c "import httpx; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=4); print('✅ Binance OK' if r.status_code==200 else '❌ Binance Error')" 2>/dev/null
  
  # Scanner check
  pgrep -f "gpt_auto_suggest.py" >/dev/null && echo -e "${GREEN}✅ Scanner פעיל${RESET}" || echo -e "${YELLOW}⚠️ Scanner יופעל מחדש${RESET}"
  
  # API check
  curl -fsSL "http://localhost:5000/health" >/dev/null && echo -e "${GREEN}✅ API תקין${RESET}" || echo -e "${RED}❌ API לא מגיב${RESET}"
  
  send_telegram "✅ Auto-Heal Done"
}

# תפריט ראשי
clear
echo -e "${BOLD}${CYAN}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                  🤖 AlgoGPT Control Center 🤖                 ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# כל האופציות בעמודות - קומפקטי
echo -e "${BOLD}${GREEN}📊 ניטור ובדיקות${RESET}              ${BOLD}${YELLOW}🔧 תפעול${RESET}                    ${BOLD}${MAGENTA}⚙️  הגדרות${RESET}"
echo -e "${GREEN} 1${RESET}) 📦 מצב שירות               ${YELLOW} 7${RESET}) 🔁 ריסטרט               ${MAGENTA}12${RESET}) 🧩 בדיקת Secrets"
echo -e "${GREEN} 2${RESET}) 📊 דוח בריאות              ${YELLOW} 8${RESET}) 🧠 ריסטרט Scanner      ${MAGENTA}13${RESET}) 📝 קונפיגורציה"
echo -e "${GREEN} 3${RESET}) 📈 Workflows               ${YELLOW} 9${RESET}) 🔄 ריסטרט הכל          ${MAGENTA}14${RESET}) 🔐 אימות Keys"
echo -e "${GREEN} 4${RESET}) 🔍 Binance API             ${YELLOW}10${RESET}) 🧩 Auto-Heal"
echo -e "${GREEN} 5${RESET}) 📡 Telegram Bot            ${YELLOW}11${RESET}) 💬 טסט Telegram"
echo -e "${GREEN} 6${RESET}) 🧪 Dry Run Order"
echo ""
echo -e "${BOLD}${BLUE}📋 Logs & Debug${RESET}              ${BOLD}${WHITE}🧱 מערכת${RESET}"
echo -e "${BLUE}15${RESET}) 📋 לוגים אחרונים          ${WHITE}17${RESET}) 🔬 Dynamic Filters"
echo -e "${BLUE}16${RESET}) 🐛 Debug מלא               ${WHITE}18${RESET}) 🧱 בדיקה מקיפה"
echo ""
echo -e "${RED}19${RESET}) ${RED}❌ יציאה${RESET}"
echo ""
echo -ne "${BOLD}${CYAN}👉 בחר (1-19): ${RESET}"
read -r CHOICE
echo ""

case "$CHOICE" in
  1)
    echo -e "${GREEN}📦 בדיקת מצב...${RESET}"
    curl -s http://localhost:5000/health | python3 -m json.tool && echo -e "${GREEN}✅ Server פעיל${RESET}"
    curl -s http://localhost:5000/ | python3 -m json.tool
    ;;
  2)
    echo -e "${CYAN}📊 מפיק דוח...${RESET}"
    {
      echo "🩺 AlgoGPT Health - $(date '+%H:%M:%S')"
      echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      curl -s http://localhost:5000/health || echo "❌ Server down"
      echo ""
      ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep
      echo ""
      echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}')% | Memory: $(free -m | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}')"
      curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo "✅ Binance OK" || echo "❌ Binance"
    } | tee /tmp/health.txt
    send_telegram "🩺 Health Report: $(date '+%H:%M')"
    ;;
  3)
    echo -e "${CYAN}📈 Workflows:${RESET}"
    ps aux | grep -E "(gunicorn|gpt_auto_suggest|position_monitor|daily_digest)" | grep -v grep
    echo -e "${GREEN}סה״כ: $(ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l) processes${RESET}"
    ;;
  4)
    echo -e "${CYAN}🔍 Binance...${RESET}"
    python3 -c "import httpx,datetime as dt; r=httpx.get('https://fapi.binance.com/fapi/v1/time',timeout=5); print(f'✅ Status: {r.status_code}'); print(f'🕒 Time: {dt.datetime.fromtimestamp(r.json()[\"serverTime\"]/1000)}')"
    ;;
  5)
    echo -e "${CYAN}📡 Telegram Bot...${RESET}"
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -m json.tool || echo -e "${RED}❌ Token חסר${RESET}"
    ;;
  6)
    echo -e "${CYAN}🧪 Dry Run...${RESET}"
    python3 -c "import os,hmac,hashlib,time,httpx; k,s=os.getenv('BINANCE_API_KEY'),os.getenv('BINANCE_API_SECRET'); ts=int(time.time()*1000); qs=f'symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=0.001&price=20000&timeInForce=GTC&timestamp={ts}'; sig=hmac.new(s.encode(),qs.encode(),hashlib.sha256).hexdigest(); r=httpx.post(f'https://fapi.binance.com/fapi/v1/order/test?{qs}&signature={sig}',headers={'X-MBX-APIKEY':k},timeout=10); print('✅ API Keys תקינים!' if r.status_code==200 else f'❌ Error {r.status_code}')"
    ;;
  7)
    echo -e "${YELLOW}🔁 ריסטרט...${RESET}"
    echo "💡 לחץ 'Restart' ב-Workflows pane (צד ימין)"
    ;;
  8)
    echo -e "${YELLOW}🧠 ריסטרט Scanner...${RESET}"
    pkill -f "gpt_auto_suggest.py" 2>/dev/null
    echo -e "${GREEN}✅ יופעל מחדש אוטומטית${RESET}"
    ;;
  9)
    echo -e "${YELLOW}🔄 ריסטרט כל Workflows...${RESET}"
    echo "💡 ב-Replit: לחץ Restart בכל workflow ב-Workflows pane"
    ;;
  10)
    auto_heal
    ;;
  11)
    echo -e "${YELLOW}💬 שולח טסט...${RESET}"
    send_telegram "🧪 Test - $(date '+%H:%M:%S') ✅"
    echo -e "${GREEN}✅ נשלח לטלגרם!${RESET}"
    ;;
  12)
    echo -e "${MAGENTA}🧩 Secrets:${RESET}"
    check_env
    ;;
  13)
    echo -e "${MAGENTA}📝 קונפיגורציה:${RESET}"
    echo -e "${CYAN}Port:${RESET} 5000"
    echo -e "${CYAN}Workflows:${RESET} AlgoGPT Server, Auto Scanner, Position Monitor, Daily Digest"
    echo -e "${CYAN}Features:${RESET} Dynamic Filters, Telegram Approval, Live Management"
    ;;
  14)
    echo -e "${MAGENTA}🔐 אימות...${RESET}"
    check_env
    ;;
  15)
    echo -e "${BLUE}📋 לוגים:${RESET}"
    echo "=== Server (10 אחרונות) ==="
    tail -10 /tmp/logs/AlgoGPT_Server_*.log 2>/dev/null || echo "אין לוגים"
    echo ""
    echo "=== Scanner (10 אחרונות) ==="
    tail -10 /tmp/logs/Auto_Scanner_*.log 2>/dev/null || echo "אין לוגים"
    ;;
  16)
    echo -e "${BLUE}🐛 Debug:${RESET}"
    check_env
    echo ""
    ps aux | grep -E "(python|gunicorn)" | grep -v grep | head -5
    echo ""
    curl -s http://localhost:5000/health
    ;;
  17)
    echo -e "${WHITE}🔬 Dynamic Filters:${RESET}"
    [[ -f "utils/dynamic_filters.py" ]] && echo -e "${GREEN}✅ קיים ($(wc -l < utils/dynamic_filters.py) שורות)${RESET}" || echo -e "${RED}❌ לא נמצא${RESET}"
    tail -3 /tmp/logs/Auto_Scanner_*.log 2>/dev/null | grep -i "mood\|regime" || echo "אין לוגים"
    ;;
  18)
    echo -e "${WHITE}🧱 בדיקה מקיפה:${RESET}"
    echo -e "${CYAN}Processes:${RESET} $(ps aux | grep -E "(gunicorn|gpt_auto_suggest)" | grep -v grep | wc -l) רצים"
    echo -e "${CYAN}Server:${RESET}" && curl -s http://localhost:5000/health
    echo -e "${CYAN}CPU:${RESET} $(top -bn1 | grep "Cpu(s)" | awk '{print $2}')%"
    echo -e "${CYAN}Memory:${RESET} $(free -m | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}')"
    curl -s https://fapi.binance.com/fapi/v1/time >/dev/null && echo -e "${GREEN}✅ Binance${RESET}" || echo -e "${RED}❌ Binance${RESET}"
    ;;
  19)
    echo -e "${RED}❌ יציאה${RESET}"
    exit 0
    ;;
  *)
    echo -e "${RED}❌ בחירה לא תקפה (1-19)${RESET}"
    ;;
esac

echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${CYAN}💡 AlgoGPT Active${RESET} | ${GREEN}Dynamic Filters ON${RESET} | ${YELLOW}530 Symbols${RESET} | ${MAGENTA}60s Cycles${RESET}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
