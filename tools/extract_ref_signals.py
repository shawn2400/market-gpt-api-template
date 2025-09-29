#!/usr/bin/env python3
import json, sys
from pathlib import Path
from datetime import datetime, timezone

def norm_side(x:str)->str:
    x=(x or "").lower()
    if x in ("long","buy","open_long","tp_long","tp1_long"): return "long"
    if x in ("short","sell","open_short","tp_short","tp1_short"): return "short"
    return "neutral"

def to_ts(val):
    if isinstance(val,(int,float)):
        return datetime.fromtimestamp(float(val)/1000.0, tz=timezone.utc).isoformat()
    s=str(val or "")
    try:
        return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return None

def main(src_path: str, dst_path: str):
    raw=json.loads(Path(src_path).read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("rows") or []
    out=[]
    for r in rows:
        ts = r.get("ts") or r.get("close_time") or r.get("time")
        side = r.get("side") or r.get("action") or r.get("dir")
        ts = to_ts(ts); side = norm_side(side)
        if ts and side in ("long","short"):
            out.append({"ts": ts, "side": side})
    Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
    Path(dst_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__=="__main__":
    if len(sys.argv)!=3:
        print("usage: extract_ref_signals.py <src_json> <dst_json>", file=sys.stderr); sys.exit(2)
    main(sys.argv[1], sys.argv[2])

