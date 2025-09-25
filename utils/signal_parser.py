# utils/signal_parser.py
from __future__ import annotations
import re
from typing import Optional, Dict, Any

# דוגמאות נתמכות:
# "BUY BTCUSDT @ 63985 qty=0.001 lev=10 tp=64200 sl=63500"
# "SELL ETHUSDT @ 2530"
SIG_RE = re.compile(
    r'(?P<side>BUY|SELL)\s+(?P<symbol>[A-Z0-9]+)\s*@\s*(?P<entry>\d+(?:\.\d+)?)'
    r'(?:.*?\bqty=(?P<qty>\d+(?:\.\d+)?))?'
    r'(?:.*?\blev(?:erage)?=(?P<lev>\d+))?'
    r'(?:.*?\btp=(?P<tp>\d+(?:\.\d+)?))?'
    r'(?:.*?\bsl=(?P<sl>\d+(?:\.\d+)?))?',
    re.IGNORECASE
)

def parse_text_signal(line: str) -> Optional[Dict[str, Any]]:
    """
    קולט שורה טקסטואלית ומחזיר dict עם:
    { side, symbol, entry, quantity?, leverage?, tp?, sl? }
    אם אין התאמה – מחזיר None.
    """
    if not line:
        return None
    m = SIG_RE.search(line)
    if not m:
        return None
    g = m.groupdict()
    out: Dict[str, Any] = {
        "side": g["side"].upper(),
        "symbol": g["symbol"].upper(),
        "entry": float(g["entry"]),
    }
    if g.get("qty"): out["quantity"] = float(g["qty"])
    if g.get("lev"): out["leverage"] = int(g["lev"])
    if g.get("tp"):  out["tp"] = float(g["tp"])
    if g.get("sl"):  out["sl"] = float(g["sl"])
    return out

