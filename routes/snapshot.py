# routes/snapshot.py
from __future__ import annotations
import os, time
from typing import Optional, Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel

# נשתמש ב-matplotlib בלי תצוגה
import matplotlib
matplotlib.use("Agg")  # ללא GUI
import matplotlib.pyplot as plt

# ✅ רק tags, בלי prefix (prefix מוגדר כבר ב-main.py)
router = APIRouter(tags=["Snapshots"])

class SnapshotTradeRequest(BaseModel):
    symbol: str
    direction: str  # LONG/SHORT
    entry: float
    sl: float
    tp: float
    price_now: Optional[float] = None
    budget: Optional[float] = None
    leverage: Optional[float] = None
    quality_score: Optional[float] = None

@router.post("/trade", operation_id="postTradeSnapshot")
def post_trade_snapshot(payload: SnapshotTradeRequest) -> Dict[str, Any]:
    # תיקייה לכתיבה
    out_dir = os.path.join("static", "snapshots")
    os.makedirs(out_dir, exist_ok=True)

    ts = int(time.time())
    fname = f"trade-{payload.symbol}-{ts}.png".replace("/", "_")
    fpath = os.path.join(out_dir, fname)

    # ציור Snapshot בסיסי
    fig = plt.figure(figsize=(6, 3.2), dpi=150)
    fig.patch.set_alpha(0.0)
    ax = plt.gca()
    ax.axis("off")

    txt = (
        f"AlgoGPT Trade Snapshot\n"
        f"Symbol: {payload.symbol} | {payload.direction}\n"
        f"Entry: {payload.entry}  SL: {payload.sl}  TP: {payload.tp}\n"
        f"Now: {payload.price_now or '-'}  "
        f"Budget: {payload.budget or '-'}  Lev: {payload.leverage or '-'}\n"
        f"Quality: {payload.quality_score or '-'}"
    )
    ax.text(0.02, 0.9, txt, transform=ax.transAxes, va="top", ha="left", fontsize=10)

    # קו פשוט עם SL/ENTRY/TP
    ax.plot([0.05, 0.95], [0.35, 0.35], lw=2)
    ax.text(0.05, 0.33, f"SL {payload.sl}", fontsize=8)
    ax.text(0.45, 0.33, f"ENTRY {payload.entry}", fontsize=8)
    ax.text(0.80, 0.33, f"TP {payload.tp}", fontsize=8)

    plt.tight_layout()
    fig.savefig(fpath, bbox_inches="tight")
    plt.close(fig)

    # בנה URL ציבורי אם קיים
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    url = f"{base}/static/snapshots/{fname}" if base else f"/static/snapshots/{fname}"

    return {"ok": True, "file_path": fpath, "url": url}




