cat > sig_manage.sh <<'SH'
#!/usr/bin/env bash
: "${BASE_URL:?}"; : "${OPS_SIGN_SECRET:?}"; : "${SYMBOL:?}"
PATH_="/manage-once/signed"; NS="${NS:-ops-supervisor-web}"
EXP=$(($(date +%s)+600))
SIG=$(python3 - <<PY
import os,hmac,hashlib,sys,string
sec=os.environ["OPS_SIGN_SECRET"]; msg="|".join([os.environ["PATH_"],os.environ["SYMBOL"],os.environ["EXP"],os.environ["NS"]]).encode()
key=bytes.fromhex(sec) if (len(sec)==64 and all(c in string.hexdigits for c in sec)) else sec.encode()
print(hmac.new(key,msg,hashlib.sha256).hexdigest())
PY
)
curl -fsS "$BASE_URL$PATH_?ticket_id=$SYMBOL&symbol=$SYMBOL&exp=$EXP&ns=$NS&sig=$SIG"
echo
SH
chmod +x sig_manage.sh
