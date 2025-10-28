# utils/env_utils.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple, Type, TypeVar

__all__ = [
    "env_raw",
    "env_str",
    "env_bool",
    "env_int",
    "env_float",
    "env_choice",
    "env_json",
    "env_list_str",
    "env_list_int",
    "env_list_float",
    "env_int_list",         # alias נפוץ
    "env_duration_seconds", # "30s" / "5m" / "2h" / "1d"
    "env_port",
]

_T = TypeVar("_T")

# -------- בסיס: קריאת ENV או קובץ סוד (FOO או FOO_FILE) --------
def _get_with_file(name: str) -> Optional[str]:
    """
    אם קיים NAME_FILE והוא מצביע לקובץ – נקרא משם (docker secrets),
    אחרת נקרא NAME רגיל. אם שניהם חסרים/ריקים – נחזיר None.
    """
    file_key = f"{name}_FILE"
    path = os.getenv(file_key)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
                return value if value != "" else None
        except Exception:
            # לא מפילים אפליקציה על סוד חסר – מחזירים None ונותנים לשכבת הוולידציה להחליט
            return None
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v if v != "" else None

def env_raw(name: str, default: Optional[str] = None) -> Optional[str]:
    """מחזיר מחרוזת ENV גולמית (מ־NAME או NAME_FILE), או default אם ריק/חסר."""
    v = _get_with_file(name)
    return v if v is not None else default

# -------- עזרים להמרות --------
_TRUE_SET = {"1", "true", "yes", "on", "y", "t"}
_FALSE_SET = {"0", "false", "no", "off", "n", "f"}

def env_bool(name: str, default: bool = False) -> bool:
    v = _get_with_file(name)
    if v is None:
        return default
    s = v.strip().lower()
    if s in _TRUE_SET:
        return True
    if s in _FALSE_SET:
        return False
    # אם ערך לא חוקי – נחזיר default (לא מפילים תהליך בפרודקשן)
    return default

def env_str(name: str, default: Optional[str] = None, *, allow_empty: bool = False) -> Optional[str]:
    v = _get_with_file(name)
    if v is None:
        return default
    if v == "" and not allow_empty:
        return default
    return v

def _clamp(val: _T, *, min_value: Optional[_T] = None, max_value: Optional[_T] = None) -> _T:
    if (min_value is not None) and val < min_value:
        return min_value
    if (max_value is not None) and val > max_value:
        return max_value
    return val

def env_int(
    name: str,
    default: Optional[int] = None,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    allow_csv_first: bool = True,
) -> Optional[int]:
    """
    קורא int בצורה קשיחה. אם התקבל CSV בטעות (למשל "1,2"), ניקח את הפריט הראשון (אם allow_csv_first=True).
    """
    v = _get_with_file(name)
    if v is None:
        return default
    s = v.strip()
    if allow_csv_first and ("," in s or ";" in s):
        s = re.split(r"[;,]", s, maxsplit=1)[0].strip()
    try:
        n = int(s, 10)
    except Exception:
        return default
    return _clamp(n, min_value=min_value, max_value=max_value)

def env_float(
    name: str,
    default: Optional[float] = None,
    *,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    allow_csv_first: bool = True,
) -> Optional[float]:
    v = _get_with_file(name)
    if v is None:
        return default
    s = v.strip()
    if allow_csv_first and ("," in s or ";" in s):
        s = re.split(r"[;,]", s, maxsplit=1)[0].strip()
    try:
        x = float(s)
    except Exception:
        return default
    return _clamp(x, min_value=min_value, max_value=max_value)

def env_choice(name: str, choices: Sequence[str], default: Optional[str] = None, *, casefold: bool = True) -> Optional[str]:
    v = _get_with_file(name)
    if v is None:
        return default
    if casefold:
        norm = {c.lower(): c for c in choices}
        vv = v.lower()
        return norm.get(vv, default)
    return v if v in choices else default

def env_json(name: str, default: Any = None) -> Any:
    v = _get_with_file(name)
    if v is None:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default

# -------- רשימות --------
def _split_list(v: str) -> List[str]:
    # תומך במפרידי פסיקים/נקודה-פסיק/שורות; מסיר ערכים ריקים
    parts = re.split(r"[,\n;]", v)
    return [p.strip() for p in parts if p.strip() != ""]

def env_list_str(name: str, default: Optional[List[str]] = None) -> List[str]:
    v = _get_with_file(name)
    if v is None or v.strip() == "":
        return default or []
    return _split_list(v)

def env_list_int(name: str, default: Optional[List[int]] = None) -> List[int]:
    v = _get_with_file(name)
    if v is None or v.strip() == "":
        return default or []
    out: List[int] = []
    for p in _split_list(v):
        try:
            out.append(int(p, 10))
        except Exception:
            # מתעלמים מערכים לא חוקיים – פרודקשן-פרנדלי
            continue
    return out

# alias נפוץ בקוד קודם
env_int_list = env_list_int

def env_list_float(name: str, default: Optional[List[float]] = None) -> List[float]:
    v = _get_with_file(name)
    if v is None or v.strip() == "":
        return default or []
    out: List[float] = []
    for p in _split_list(v):
        try:
            out.append(float(p))
        except Exception:
            continue
    return out

# -------- זמנים/דורסיונים --------
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)(ms|s|m|h|d)?\s*$", re.IGNORECASE)
def _unit_seconds(unit: Optional[str]) -> float:
    if not unit:
        return 1.0
    u = unit.lower()
    if u == "ms":
        return 0.001
    if u == "s":
        return 1.0
    if u == "m":
        return 60.0
    if u == "h":
        return 3600.0
    if u == "d":
        return 86400.0
    return 1.0

def _parse_duration_fragment(s: str) -> Optional[float]:
    m = _DURATION_RE.match(s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    return num * _unit_seconds(unit)

def env_duration_seconds(name: str, default: Optional[float] = None, *, clamp_min: Optional[float] = None, clamp_max: Optional[float] = None) -> Optional[float]:
    """
    תומך בפורמטים:
      - "30" (שניות)
      - "500ms" / "2s" / "5m" / "1.5h" / "1d"
      - משולב עם מפרידים: "1m,30s" או "1m30s" → סכום
    מחזיר float שניות (או default אם ריק/לא חוקי).
    """
    v = _get_with_file(name)
    if v is None or v.strip() == "":
        return default
    s = v.strip()
    # תמיכה ב"1m30s" ע"י פיצול על יחידות
    # נפרק גם על פסיקים/נקודה-פסיק/רווחים
    tokens = re.findall(r"\d+(?:\.\d+)?(?:ms|s|m|h|d)?", s, flags=re.IGNORECASE)
    if not tokens:
        # fallback: נסה ישיר
        single = _parse_duration_fragment(s)
        if single is None:
            return default
        total = single
    else:
        total = 0.0
        for t in tokens:
            frag = _parse_duration_fragment(t)
            if frag is None:
                # דלג – לא מפילים אפליקציה
                continue
            total += frag
    if clamp_min is not None and total < clamp_min:
        total = clamp_min
    if clamp_max is not None and total > clamp_max:
        total = clamp_max
    return total

# -------- פורט --------
def env_port(name: str = "PORT", default: int = 8000) -> int:
    n = env_int(name, default=default, min_value=1, max_value=65535)
    return int(n if n is not None else default)

# -------- דוגמת שימוש עצמית (לא נדרשת בפרודקשן) --------
if __name__ == "__main__":
    # הדגמות קצרות; לא מריצים בפרודקשן
    os.environ["X_BOOL"] = "yes"
    os.environ["X_INT"] = "  42 "
    os.environ["X_FLOAT"] = "3.14"
    os.environ["X_CSV"] = "1,2,3"
    os.environ["X_IDS"] = "449087907, 123456789;  , 9999"
    os.environ["X_DUR"] = "1m30s"
    print("env_bool:", env_bool("X_BOOL"))
    print("env_int :", env_int("X_INT"))
    print("env_float:", env_float("X_FLOAT"))
    print("env_list_int:", env_list_int("X_IDS"))
    print("env_int_list:", env_int_list("X_IDS"))
    print("env_duration_seconds:", env_duration_seconds("X_DUR"))

