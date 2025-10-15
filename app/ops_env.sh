cat >/app/ops_env.sh <<'BASH'
#!/usr/bin/env bash
# === AlgoGPT ops env (persist) ===
export PUBLIC_HOST="https://algogpt-docker.onrender.com"
export API_BEARER_TOKEN="rnd_XVyANQbo1mk8Q8nny3kTNDEzKoF7"
export OPS_SIGN_SECRET="51d4ad23aebf0ce08fc7d80fc265e02406a9075a7b5876cfe49296adc0c1821f"
export API_SIGNING_SECRET="$OPS_SIGN_SECRET"
export REDIS_URL='rediss://red-d2j4vf2li9vc73evhv4g:lW8H0fqByUjWpiIlITKuGi6sncAI6848@frankfurt-keyvalue.render.com:6379?ssl_cert_reqs=required&socket_connect_timeout=5&socket_timeout=5'
BASH
