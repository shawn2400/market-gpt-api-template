# utils/watchlist_utils.py

import os
import json
import logging
from typing import Any, Dict, List, Optional

# ניתן להגדיר מיקום קובץ דרך משתנה סביבה; אחרת ברירת־מחדל watchlist.json בשורש
WATCHLIST_FILE = os.getenv("WATCHLIST_JSON", "watchlist.json")

# --------- עזר לנרמול ---------
def _normalize_item(x: Any) -> Optional[Dict[str, Any]]:
    """
    מקבל פריט Watchlist בכל פורמט הגיוני ומחזיר dict תקני לפחות עם 'symbol'.
    תומך:
      - {"symbol": "BTCUSDT", "direction": "LONG", "quality_score": 8}
      - {"ticker": "BTCUSDT"} / {"s": "BTCUSDT"}
      - {"BTCUSDT": 8}  (מפה של סימבול->ציון)
      - "BTCUSDT"       (מחרוזת בלבד)
    """
    if isinstance(x, dict):
        # קודם חפש מפתח סימבול קלאסי
        sym = x.get("symbol") or x.get("ticker") or x.get("s")
        if not sym and len(x) == 1:
            # מקרה {"BTCUSDT": 8}
            k = next(iter(x.keys()))
            sym = k
            # אם יש ערך יחיד והוא מספרי -> quality_score
            v = x[k]
            try:
                qs = float(v)
            except Exception:
                qs = None
            out = {"symbol": str(sym).upper()}
            if qs is not None:
                out["quality_score"] = qs
            # נסה לשמר direction אם קיים בצד השני (לא רלוונטי פה)
            if "direction" in x:
                out["direction"] = x["direction"]
            return out

        if not sym:
            return None

        out = {"symbol": str(sym).upper()}

        # העתק שדות רלוונטיים אם קיימים
        if "direction" in x and isinstance(x["direction"], str):
            d = x["direction"].strip().upper()
            out["direction"] = "LONG" if d in ("LONG", "BUY") else ("SHORT" if d in ("SHORT", "SELL") else d)

        # quality_score -> מספר
        q = x.get("quality_score")
        if q is not None:
            try:
                out["quality_score"] = float(q)
            except Exception:
                pass

        # שדות נוספים אם תרצה לשמר
        for k in ("note", "source", "trend", "ts"):
            if k in x:
                out[k] = x[k]

        return out

    if isinstance(x, str):
        s = x.strip().upper()
        return {"symbol": s} if s else None

    # טיפוסים אחרים – לא נתמך
    return None


def _dedupe_keep_order(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ייחוד לפי symbol תוך שמירה על סדר הופעה."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for d in items:
        s = d.get("symbol")
        if not s:
            continue
        if s not in seen:
            seen.add(s)
            out.append(d)
    return out


# --------- טעינה/שמירה ---------
def load_watchlist(min_quality: float = 0) -> List[Dict[str, Any]]:
    """
    טוען את קובץ watchlist.json ומחזיר רשימת dict-ים מנורמלת:
    [{ 'symbol': 'BTCUSDT', 'direction': 'LONG'|'SHORT'?, 'quality_score': float? }, ...]
    מבצע:
      - נרמול פורמטים שונים
      - Uppercase ל-symbol
      - סינון לפי min_quality
      - ייחוד סמלים
    במקרה של שגיאה – מחזיר [] ולא מפיל את השרת.
    """
    try:
        if not os.path.exists(WATCHLIST_FILE):
            logging.error(f"[watchlist] File not found: {WATCHLIST_FILE}")
            return []

        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, list):
            logging.error(f"[watchlist] Invalid data format: expected list, got {type(raw)}")
            return []

        normalized: List[Dict[str, Any]] = []
        skipped = 0
        for item in raw:
            ni = _normalize_item(item)
            if ni and ni.get("symbol"):
                normalized.append(ni)
            else:
                skipped += 1

        # סינון לפי איכות (אם יש שדה; אם אין, מתייחס כ-0)
        def _qs(x: Dict[str, Any]) -> float:
            q = x.get("quality_score", 0)
            try:
                return float(q)
            except Exception:
                return 0.0

        if min_quality and min_quality > 0:
            normalized = [d for d in normalized if _qs(d) >= float(min_quality)]

        # ייחוד ושמירת סדר
        unique_list = _dedupe_keep_order(normalized)

        logging.info(f"[watchlist] Loaded {len(unique_list)} symbols above quality {min_quality}"
                     + (f" (skipped {skipped} invalid items)" if skipped else ""))
        return unique_list

    except json.JSONDecodeError as e:
        logging.error(f"[watchlist] JSON decode error: {e}")
        return []
    except Exception as e:
        logging.error(f"[watchlist] Unexpected error: {e}", exc_info=True)
        return []


def save_watchlist(items: List[Dict[str, Any]]) -> bool:
    """
    שומר רשימת dict-ים (מנורמלת) ל־WATCHLIST_FILE בצורה בטוחה.
    מחזיר True אם הצליח.
    """
    try:
        # ודא נרמול לפני שמירה (למקרה שנכנסה רשימה היברידית)
        norm = []
        for it in (items or []):
            ni = _normalize_item(it)
            if ni:
                norm.append(ni)
        norm = _dedupe_keep_order(norm)

        with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
            json.dump(norm, f, ensure_ascii=False, indent=2)
        logging.info(f"[watchlist] Saved {len(norm)} items to {WATCHLIST_FILE}")
        return True
    except Exception as e:
        logging.error(f"[watchlist] Failed saving to {WATCHLIST_FILE}: {e}", exc_info=True)
        return False


# --------- נוחות לצרכנים ---------
def get_symbols_list(min_quality: float = 0) -> List[str]:
    """
    מחזיר רשימת סמלים (str בלבד) לאחר נרמול וסינון.
    נוח לשימוש עם סורקים/WS כאשר לא צריך את המטא־דאטה.
    """
    wl = load_watchlist(min_quality=min_quality)
    syms = [d["symbol"] for d in wl if isinstance(d, dict) and d.get("symbol")]
    # שמירה על ייחוד (ליתר ביטחון) ושמירת סדר
    out = []
    seen = set()
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def upsert_symbol(symbol: str, quality_score: Optional[float] = None, direction: Optional[str] = None) -> bool:
    """
    מוסיף/מעדכן סימבול ב-watchlist עם שדות אופציונליים.
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        logging.error("[watchlist] upsert_symbol: empty symbol")
        return False

    wl = load_watchlist(min_quality=0)
    # חפש קיים
    idx = next((i for i, d in enumerate(wl) if d.get("symbol") == symbol), None)
    if idx is None:
        entry: Dict[str, Any] = {"symbol": symbol}
        if quality_score is not None:
            try:
                entry["quality_score"] = float(quality_score)
            except Exception:
                pass
        if direction:
            d = direction.strip().upper()
            entry["direction"] = "LONG" if d in ("LONG", "BUY") else ("SHORT" if d in ("SHORT", "SELL") else d)
        wl.append(entry)
    else:
        if quality_score is not None:
            try:
                wl[idx]["quality_score"] = float(quality_score)
            except Exception:
                pass
        if direction:
            d = direction.strip().upper()
            wl[idx]["direction"] = "LONG" if d in ("LONG", "BUY") else ("SHORT" if d in ("SHORT", "SELL") else d)

    return save_watchlist(wl)












