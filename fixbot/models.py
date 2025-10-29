# fixbot/models.py
from __future__ import annotations
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class ScanReq(BaseModel):
    feature: str                # נושא: "ניהול דינמי אוטומטי"
    hints: List[str] = []       # שמות קבצים/פונקציות: ["manage_open_trades", "trade_manager.py"]
    include_globs: List[str] = []
    exclude_globs: List[str] = ["**/.venv/**","**/node_modules/**",".git/**","dist/**","build/**"]
    shell_output: str = ""      # כאן נדביק פלט SHELL/pytest/build

class ScanResp(BaseModel):
    plan_id: str
    summary: str
    affected_files: List[str]
    issues: List[Dict[str,Any]]
    proposed_changes: List[Dict[str,Any]]
    next_step: str

class ApplyReq(BaseModel):
    plan_id: str
    branch: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None

class ApplyResp(BaseModel):
    ok: bool
    branch: str
    pr_url: str
