cat >/app/ops_env.sh <<'BASH'
#!/usr/bin/env bash
# === AlgoGPT ops env ===
# עדכן את הערכים האמיתיים שלך:
export PUBLIC_HOST="https://algogpt-docker.onrender.com"
export API_BEARER_TOKEN="<<<PUT-YOUR-BEARER-TOKEN>>>"
export OPS_SIGN_SECRET="<<<PUT-YOUR-OPS_SIGN_SECRET>>>"
export API_SIGNING_SECRET="$OPS_SIGN_SECRET"
BASH
