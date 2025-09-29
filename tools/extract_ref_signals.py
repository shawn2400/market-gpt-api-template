#!/usr/bin/env python3
import json, sys
from pathlib import Path
from datetime import datetime, timezone

# קלט: path לקובץ JSON, פלט: רשימת ref_signals בפורמט [{"ts": "...", "side": "..."}]
# תומך בשדות נפוצים: ts/close_time, side, action, status

def norm_side(x:str)->str:
    x=(x or "").lower()
    if x in ("long","buy","open_long","tp_long","tp1_long"): return "long"
    if x in ("short","sell","open_short","tp_short","tp1_short"): return "short"
    return "neutral"

def to_ts(val):
    # תומך epoch ms/iso8601
    if isinstance(val,(int,float)): 
        return datetime.fromtimestamp(float(val)/1000.0, tz=timezone.utc).isoformat()
    s=str(val)
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return None

def main(pth):
    raw=json.loads(Path(pth).read_text(encoding="utf-8"))
    out=[]
    rows = raw if isinstance(raw, list) else raw.get("rows") or []
    for r in rows:
        ts = r.get("ts") or r.get("close_time") or r.get("time")
        side = r.get("side") or r.get("action") or r.get("dir")
        ts = to_ts(ts)
        side = norm_side(side)
        if ts and side in ("long","short"):
            out.append({"ts": ts, "side": side})
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__=="__main__":
    if len(sys.argv)<2:
        print("usage: extract_ref_signals.py /path/to/trades_log.json", file=sys.stderr); sys.exit(2)
    main(sys.argv[1])
