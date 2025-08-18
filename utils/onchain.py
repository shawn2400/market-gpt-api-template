# utils/onchain.py  (אופציונלי; מינימלי)
from __future__ import annotations
from typing import List, Dict, Any

def overview(chains: List[str]) -> Dict[str, Any]:
    # placeholder – להחליף כשמחברים ספק אמיתי
    out={}
    for c in chains:
        out[c] = {"ok": True, "fees": None, "stats": None, "warnings": ["placeholder"]}
    return out



