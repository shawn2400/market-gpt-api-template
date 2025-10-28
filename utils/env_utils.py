# utils/env_utils.py
from __future__ import annotations
import os
from typing import List, Optional

def env_bool(name: str, default: bool=False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1","true","yes","on")

def env_int(name: str, default: Optional[int]=None) -> Optional[int]:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(str(v).strip())
    except Exception:
        # אם הגיע CSV בטעות – ננסה לקחת את הפריט הראשון
        s = str(v).split(",")[0].strip()
        return int(s)

def env_int_list(name: str, default: Optional[List[int]]=None) -> List[int]:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default or []
    out: List[int] = []
    for part in str(v).replace(";",",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except Exception:
            # דלג על ערכים לא חוקיים
            continue
    return out
