# utils/export_utils.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def save_json(obj: Any, path: str | Path) -> bool:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[export_utils] Error saving to {path}: {e}")
        return False


