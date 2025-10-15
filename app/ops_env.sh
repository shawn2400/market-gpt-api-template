#!/usr/bin/env bash
# --- AlgoGPT ops env ---
# עדכן אם צריך:
export PUBLIC_HOST="https://algogpt-docker.onrender.com"

# שים כאן את ה-Bearer מה־Render (לא של הדוגמה!)
export API_BEARER_TOKEN="<<<PUT-YOUR-BEARER-TOKEN>>>"

# אותו הסיקרט שמוגדר ב-Render תחת OPS_SIGN_SECRET / API_SIGNING_SECRET
export OPS_SIGN_SECRET="<<<PUT-YOUR-OPS_SIGN_SECRET>>>"

# נשמור תאימות
export API_SIGNING_SECRET="$OPS_SIGN_SECRET"
