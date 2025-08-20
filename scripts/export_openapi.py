# scripts/export_openapi.py
from __future__ import annotations
import os
import json
import yaml
import sys

# מאפשר להריץ גם מתוך scripts/
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from main import app  # נטען את FastAPI app שלך

def export_openapi_yaml(out_path: str = "openapi.yaml"):
    schema = app.openapi()
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(schema, f, sort_keys=False, allow_unicode=True)
    print(f"✅ OpenAPI schema exported to {out_path}")

def export_openapi_json(out_path: str = "openapi.json"):
    schema = app.openapi()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"✅ OpenAPI schema exported to {out_path}")

if __name__ == "__main__":
    fmt = os.getenv("FORMAT", "yaml").lower()
    if fmt == "json":
        export_openapi_json()
    else:
        export_openapi_yaml()
