# fixbot/server.py
from __future__ import annotations
import os, json, shutil, tempfile, subprocess, uuid
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .feature_scan import build_repo_map, analyze_feature_area
from .plan_engine import build_fix_plan, apply_plan_changes

GITHUB_REPO = os.getenv("GITHUB_REPO")  # "owner/repo"
GH_TOKEN    = os.getenv("GH_TOKEN")     # fine-grained: contents rw, pull_requests wr
BASE_BRANCH = os.getenv("BASE_BRANCH","main")
BOT_NAME    = os.getenv("BOT_NAME","fixbot")
BOT_EMAIL   = os.getenv("BOT_EMAIL","fixbot@local")

app = FastAPI(title="Approve&Fix Agent", version="0.2.0")

class ScanReq(BaseModel):
    feature: str                         # למשל: "ניהול דינמי אוטומטי"
    hints: List[str] = []                # רמזים: שמות קבצים/פונקציות ("manage_open_trades", "trade_manager.py")
    include_globs: List[str] = []        # אופציונלי: ["utils/**", "routes/**"]
    exclude_globs: List[str] = ["**/.venv/**","**/node_modules/**",".git/**","dist/**","build/**"]

class ScanResp(BaseModel):
    plan_id: str
    summary: str
    affected_files: List[str]
    issues: List[Dict[str,Any]]          # [{type, file, detail}]
    proposed_changes: List[Dict[str,Any]]# [{action, file, description}]
    next_step: str

class ApplyReq(BaseModel):
    plan_id: str
    branch: Optional[str] = None         # אם ריק, יווצר "fix/<plan_id>"
    title: Optional[str
