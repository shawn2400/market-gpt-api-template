# utils/watchlist_utils.py
from __future__ import annotations
import os, json, logging, math
from typing import List, Dict, Any, Optional, Tuple

from utils.redis_client import redis_client  # None אם לא קונפוגרד

WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "watchlist.json")
ANCHOR_SYMBOL = "BTCUSDT"
REDIS_KEY     = "algogpt:watchlist"
REDIS_TTL     = int(os.getenv("WATCHLIST_REDIS_TTL", "3600"))

logger = logging.getLogger("algogpt.watchlist")

# ברירת מחדל קשיחה – אם אין קובץ ואין Redis
_DEFAULT_WATCHLIST: List[Dict[str, Any]] = [
    {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8},
    {"symbol": "ETHUSDT",    "direction": "LONG", "quality_score": 7},
    {"symbol": "BNBUSDT",    "direction": "LONG", "quality_score": 7},
]

# -------- Helpers --------
def _ensure_file(path: str = WATCHLIST_PATH) -> None:
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_DEFAULT_WATCHLIST, f, ensure_ascii=False, indent=2)
            logger.info({"event": "watchlist_init", "msg": f"created default {path}"})
        except Exception as e:
            logger.error({"event": "watchlist_init_error", "error": str(e)})

def _to_upper_str(x) -> Optional[str]:
    return str(x).strip().upper() if x is not None else None

def _validate_item(it: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    תומך בשדות רשות לשיכוך עומס ולקונפיג עדין:
      - weight:     0.1–10 (ברירת מחדל 1.0)
      - modes:      ["FUTURES","SPOT","GRID"] או מחרוזת comma
      - max_leverage: 1–125 (עבור FUTURES)
      - budget_usd:   float (רמז לתקציב לכל טרייד)
      - min_rr:       float (רף RR מינימלי מועדף לסימבול)
      - grid_levels:  [min, max] או int (רמז לגריד)
      - grid_step_pct: float (רמז לגריד)
      - notes:        טקסט חופשי (לא משפיע על חישובים)
    """
    try:
        sym = _to_upper_str(it.get("symbol"))
        if not sym:
            return None

        out: Dict[str, Any] = {"symbol": sym}

        # direction (לא מחייב; LONG/SHORT)
        direction = it.get("direction")
        if direction:
            d = _to_upper_str(direction)
            if d in ("LONG", "SHORT"):
                out["direction"] = d

        # quality_score (int)
        q = it.get("quality_score")
        if q is not None:
            try:
                out["quality_score"] = int(q)
            except Exception:
                pass

        # weight (float 0.1–10)
        w = it.get("weight")
        if w is not None:
            try:
                wf = float(w)
                if 0.1 <= wf <= 10.0:
                    out["weight"] = wf
            except Exception:
                pass

        # modes
        modes = it.get("modes")
        modes_list: Optional[List[str]] = None
        if isinstance(modes, list):
            modes_list = [ _to_upper_str(m) for m in modes if _to_upper_str(m) in ("FUTURES","SPOT","GRID") ]
        elif isinstance(modes, str):
            parts = [ _to_upper_str(p) for p in modes.split(",") ]
            modes_list = [p for p in parts if p in ("FUTURES","SPOT","GRID")]
        if modes_list:
            modes_list = sorted(set(modes_list))
            out["modes"] = modes_list

        # max_leverage
        ml = it.get("max_leverage")
        if ml is not None:
            try:
                mli = int(ml)
                if 1 <= mli <= 125:
                    out["max_leverage"] = mli
            except Exception:
                pass

        # budget_usd
        bud = it.get("budget_usd")
        if bud is not None:
            try:
                out["budget_usd"] = float(bud)
            except Exception:
                pass

        # min_rr
        mrr = it.get("min_rr")
        if mrr is not None:
            try:
                out["min_rr"] = float(mrr)
            except Exception:
                pass

        # grid hints
        gl = it.get("grid_levels")
        if isinstance(gl, list) and len(gl) == 2:
            try:
                gmin, gmax = int(gl[0]), int(gl[1])
                if 2 <= gmin <= gmax <= 100:
                    out["grid_levels"] = [gmin, gmax]
            except Exception:
                pass
        elif isinstance(gl, int):
            if 2 <= gl <= 100:
                out["grid_levels"] = gl

        gstep = it.get("grid_step_pct")
        if gstep is not None:
            try:
                out["grid_step_pct"] = float(gstep)
            except Exception:
                pass

        # notes
        if "notes" in it:
            try:
                out["notes"] = str(it["notes"])
            except Exception:
                pass

        return out
    except Exception:
        return None

def _ensure_anchor(watchlist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not any(it.get("symbol") == ANCHOR_SYMBOL for it in watchlist):
        watchlist.insert(0, {"symbol": ANCHOR_SYMBOL, "direction": "LONG", "quality_score": 8})
        logger.info({"event": "watchlist_anchor", "msg": f"{ANCHOR_SYMBOL} enforced"})
    return watchlist

# -------- Load / Save --------
def load_watchlist(min_quality: Optional[int] = None, path: str = WATCHLIST_PATH) -> List[Dict[str, Any]]:
    data: Optional[List[Dict[str, Any]]] = None

    # נסה קודם Redis
    if redis_client:
        try:
            raw = redis_client.get(REDIS_KEY)
            if raw:
                data = json.loads(raw)
                logger.info({"event": "watchlist_load", "src": "redis", "count": len(data)})
        except Exception as e:
            logger.warning({"event": "watchlist_redis_error", "error": str(e)})

    # אם אין ב־Redis – קובץ
    if not data:
        _ensure_file(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("watchlist must be a list")
            logger.info({"event": "watchlist_load", "src": "file", "count": len(data)})
            # סנכרון ל־Redis
            if redis_client:
                try:
                    redis_client.set(REDIS_KEY, json.dumps(data), ex=REDIS_TTL or None)
                except Exception:
                    pass
        except Exception as e:
            logger.error({"event": "watchlist_load_error", "error": str(e)})
            data = list(_DEFAULT_WATCHLIST)

    # Validate + Filter
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        v = _validate_item(item)
        if not v:
            continue
        sym = v["symbol"]
        if sym in seen:
            continue
        if isinstance(min_quality, int) and sym != ANCHOR_SYMBOL:
            q = v.get("quality_score")
            if isinstance(q, int) and q < min_quality:
                continue
        seen.add(sym)
        out.append(v)

    out = _ensure_anchor(out)
    # סדר: איכות יורד → משקל יורד → אלפבית
    def _score_key(d: Dict[str, Any]) -> Tuple[float, float, str]:
        q = float(d.get("quality_score", -1))
        w = float(d.get("weight", 1.0))
        return (-(q), -(w), d["symbol"])

    out.sort(key=_score_key)
    return out

def save_watchlist(items: List[Dict[str, Any]], path: str = WATCHLIST_PATH) -> bool:
    try:
        clean: List[Dict[str, Any]] = []
        seen = set()
        for it in items:
            v = _validate_item(it)
            if not v:
                continue
            sym = v["symbol"]
            if sym in seen:
                continue
            seen.add(sym)
            clean.append(v)

        clean = _ensure_anchor(clean)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)

        if redis_client:
            try:
                redis_client.set(REDIS_KEY, json.dumps(clean), ex=REDIS_TTL or None)
                logger.info({"event": "watchlist_save", "dst": "redis+file", "count": len(clean)})
            except Exception as e:
                logger.error({"event": "watchlist_save_redis_error", "error": str(e)})
        else:
            logger.info({"event": "watchlist_save", "dst": "file", "count": len(clean)})

        return True
    except Exception as e:
        logger.error({"event": "watchlist_save_error", "error": str(e)})
        return False

# -------- Utilities לשימוש בוורקרים / GPT --------
def list_symbols(min_quality: Optional[int] = None) -> List[str]:
    wl = load_watchlist(min_quality=min_quality)
    return [it["symbol"] for it in wl]

def get_symbol_prefs(symbol: str) -> Dict[str, Any]:
    """
    מחזיר פרמטרים פר-סימבול (אם קיימים ב־watchlist):
      direction, modes, max_leverage, budget_usd, min_rr, grid_levels, grid_step_pct, weight, quality_score
    """
    sym = symbol.strip().upper()
    for it in load_watchlist():
        if it["symbol"] == sym:
            return {
                k: it.get(k) for k in (
                    "direction","modes","max_leverage","budget_usd","min_rr",
                    "grid_levels","grid_step_pct","weight","quality_score"
                ) if k in it
            }
    return {}

def build_symbol_pool(
    *,
    k: int = 12,
    min_quality: int = 6,
    include_anchor: bool = True,
    include_shorts: bool = True,
    balanced: bool = True,
    explore_prob: float = 0.15
) -> List[str]:
    """
    Top-K דינאמי “ללא עומס”:
      - איכות × משקל
      - איזון LONG/SHORT אם balanced=True
      - חיפוש אקראי קטן (explore) למניעת “קיפאון”
    """
    wl = load_watchlist(min_quality=min_quality)
    if not wl:
        return [ANCHOR_SYMBOL]

    # ניקוד
    scored: List[Tuple[str, float, str]] = []
    for it in wl:
        sym = it["symbol"]
        q   = float(it.get("quality_score", 0))
        w   = float(it.get("weight", 1.0))
        dir0 = it.get("direction") or "LONG"
        score = q * w
        scored.append((sym, score, dir0))

    # מיון
    scored.sort(key=lambda x: (-x[1], x[0]))

    # Anchor תמיד ראשון (אם רוצים)
    out: List[str] = []
    if include_anchor and all(s != ANCHOR_SYMBOL for s, _, _ in scored):
        out.append(ANCHOR_SYMBOL)

    # איזון כיוונים
    longs = [s for s, _, d in scored if d == "LONG"]
    shorts = [s for s, _, d in scored if d == "SHORT"]

    if not include_shorts:
        pool = longs
    elif balanced:
        # שלב/רנדום קל
        L = len(longs)
        S = len(shorts)
        mix: List[str] = []
        i = j = 0
        while len(mix) < max(L, S):
            if i < L:
                mix.append(longs[i]); i += 1
            if j < S:
                mix.append(shorts[j]); j += 1
        pool = mix
    else:
        pool = [s for s, _, _ in scored]

    # חיפוש אקראי מתון (exploration)
    final: List[str] = []
    seen = set(out)
    for s in pool:
        if s in seen:
            continue
        if len(final) + len(out) >= k:
            break
        final.append(s)
        seen.add(s)

    # הזרקת Explore (במקרה ויש עודף סמלים)
    leftovers = [s for s, _, _ in scored if s not in seen]
    import random
    for s in leftovers:
        if len(final) + len(out) >= k:
            break
        if random.random() < explore_prob:
            final.append(s)

    return (out + final)[:k]



















