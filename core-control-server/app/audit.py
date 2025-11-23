from datetime import datetime
from pathlib import Path

def audit(log_path: str, event: str):
    """Log event to audit file"""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} | {event}\n")
