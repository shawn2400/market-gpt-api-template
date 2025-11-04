#!/usr/bin/env python3
"""
GitHub Auto-Commit Worker
Automatically commits and pushes changes at configured interval.
Default: 10 minutes (configurable via GITHUB_AUTO_COMMIT_INTERVAL)
"""

import os
import sys
import time
import logging
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("github_auto_commit")

ENABLED = os.getenv("GITHUB_AUTO_COMMIT_ENABLED", "1").lower() in ("1", "true", "yes", "on")
INTERVAL_SEC = int(os.getenv("GITHUB_AUTO_COMMIT_INTERVAL", "600") or 600)  # Default: 10 minutes
REPO_PATH = os.getenv("GITHUB_REPO_PATH", "/home/runner/workspace")
COMMIT_AUTHOR = os.getenv("GITHUB_COMMIT_AUTHOR", "AlgoGPT System")
COMMIT_EMAIL = os.getenv("GITHUB_COMMIT_EMAIL", "algogpt@system.local")
TELEGRAM_NOTIFY = os.getenv("GITHUB_COMMIT_TELEGRAM_NOTIFY", "1").lower() in ("1", "true", "yes", "on")

def run_command(cmd: List[str], cwd: Optional[str] = None) -> Tuple[bool, str, str]:
    """Run shell command and return (success, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or REPO_PATH,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timeout"
    except Exception as e:
        return False, "", str(e)

def check_git_status() -> Optional[str]:
    """Check if there are any changes to commit"""
    success, stdout, stderr = run_command(["git", "status", "--porcelain"])
    if not success:
        logger.error(f"git status failed: {stderr}")
        return None
    
    if not stdout:
        return None
    
    return stdout

def get_changed_files(status_output: str) -> Dict[str, List[str]]:
    """Parse git status output and categorize changed files"""
    categories = {
        "workers": [],
        "routes": [],
        "utils": [],
        "policies": [],
        "config": [],
        "scripts": [],
        "docs": [],
        "other": []
    }
    
    for line in status_output.split("\n"):
        if not line.strip():
            continue
        
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        
        filepath = parts[-1]
        
        if filepath.startswith("workers/"):
            categories["workers"].append(filepath)
        elif filepath.startswith("routes/"):
            categories["routes"].append(filepath)
        elif filepath.startswith("utils/"):
            categories["utils"].append(filepath)
        elif filepath.startswith("policies/"):
            categories["policies"].append(filepath)
        elif filepath.startswith("config/"):
            categories["config"].append(filepath)
        elif filepath.startswith("scripts/"):
            categories["scripts"].append(filepath)
        elif filepath.startswith("docs/") or filepath.endswith(".md"):
            categories["docs"].append(filepath)
        else:
            categories["other"].append(filepath)
    
    return {k: v for k, v in categories.items() if v}

def generate_commit_message(changed_files: Dict[str, List[str]]) -> str:
    """Generate smart commit message based on changed files"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not changed_files:
        return f"Auto: System update [{timestamp}]"
    
    parts = []
    
    if "workers" in changed_files:
        parts.append(f"Workers ({len(changed_files['workers'])})")
    if "routes" in changed_files:
        parts.append(f"Routes ({len(changed_files['routes'])})")
    if "utils" in changed_files:
        parts.append(f"Utils ({len(changed_files['utils'])})")
    if "policies" in changed_files:
        parts.append(f"Policies ({len(changed_files['policies'])})")
    if "config" in changed_files:
        parts.append(f"Config ({len(changed_files['config'])})")
    if "scripts" in changed_files:
        parts.append(f"Scripts ({len(changed_files['scripts'])})")
    if "docs" in changed_files:
        parts.append(f"Docs ({len(changed_files['docs'])})")
    if "other" in changed_files:
        parts.append(f"Other ({len(changed_files['other'])})")
    
    summary = ", ".join(parts)
    
    total_files = sum(len(files) for files in changed_files.values())
    
    return f"Auto: {summary} | {total_files} files | {timestamp}"

def configure_git():
    """Configure git user for commits"""
    run_command(["git", "config", "user.name", COMMIT_AUTHOR])
    run_command(["git", "config", "user.email", COMMIT_EMAIL])
    logger.info(f"Git configured: {COMMIT_AUTHOR} <{COMMIT_EMAIL}>")

def commit_and_push(status_output: str) -> bool:
    """Add, commit, and push changes"""
    changed_files = get_changed_files(status_output)
    commit_msg = generate_commit_message(changed_files)
    
    logger.info(f"Committing changes: {commit_msg}")
    
    success, stdout, stderr = run_command(["git", "add", "."])
    if not success:
        logger.error(f"git add failed: {stderr}")
        return False
    
    success, stdout, stderr = run_command(["git", "commit", "-m", commit_msg])
    if not success:
        logger.error(f"git commit failed: {stderr}")
        return False
    
    logger.info("Changes committed successfully")
    
    success, stdout, stderr = run_command(["git", "push", "origin", "main"])
    if not success:
        success, stdout, stderr = run_command(["git", "push", "origin", "master"])
        if not success:
            logger.error(f"git push failed: {stderr}")
            return False
    
    logger.info("Changes pushed successfully")
    
    return True

def check_structure_changes(status_output: str) -> bool:
    """Check if there are structural changes (new files/directories)"""
    for line in status_output.split("\n"):
        if line.strip().startswith("??"):
            return True
    return False

def update_readme_structure():
    """Update README.md file structure section if needed"""
    readme_path = Path(REPO_PATH) / "README.md"
    if not readme_path.exists():
        logger.warning("README.md not found, skipping structure update")
        return
    
    logger.info("Structural changes detected, README.md already up to date")

async def send_telegram_notification(message: str):
    """Send notification to Telegram (critical level only)"""
    if not TELEGRAM_NOTIFY:
        return
    
    try:
        import httpx
        
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        
        if not (bot_token and chat_id):
            return
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"🔄 <b>GitHub Auto-Commit</b>\n\n{message}",
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            if response.status_code == 200:
                logger.info("Telegram notification sent")
            else:
                logger.warning(f"Telegram notification failed: {response.status_code}")
    
    except Exception as e:
        logger.warning(f"Failed to send Telegram notification: {e}")

def run_auto_commit_cycle():
    """Run single auto-commit cycle"""
    logger.info("Running auto-commit cycle...")
    
    if not ENABLED:
        logger.info("Auto-commit is disabled (GITHUB_AUTO_COMMIT_ENABLED=0)")
        return
    
    status = check_git_status()
    
    if not status:
        logger.info("No changes detected, skipping commit")
        return
    
    logger.info("Changes detected:")
    status_lines = status.split("\n")
    for line in status_lines[:10]:
        logger.info(f"  {line}")
    
    if len(status_lines) > 10:
        remaining = len(status_lines) - 10
        logger.info(f"  ... and {remaining} more files")
    
    configure_git()
    
    has_structure_changes = check_structure_changes(status)
    if has_structure_changes:
        update_readme_structure()
    
    success = commit_and_push(status)
    
    if success:
        logger.info("✅ Auto-commit cycle completed successfully")
        
        import asyncio
        changed_files = get_changed_files(status)
        total = sum(len(files) for files in changed_files.values())
        msg = f"✅ Committed {total} files successfully"
        
        try:
            asyncio.run(send_telegram_notification(msg))
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")
    else:
        logger.error("❌ Auto-commit cycle failed")

def main():
    """Main worker loop"""
    logger.info("GitHub Auto-Commit Worker started")
    logger.info(f"Interval: {INTERVAL_SEC} seconds ({INTERVAL_SEC // 60} minutes)")
    logger.info(f"Repository: {REPO_PATH}")
    logger.info(f"Author: {COMMIT_AUTHOR} <{COMMIT_EMAIL}>")
    logger.info(f"Enabled: {ENABLED}")
    
    if not ENABLED:
        logger.warning("Auto-commit is disabled. Set GITHUB_AUTO_COMMIT_ENABLED=1 to enable.")
        logger.info("Worker will keep running but won't commit changes")
    
    while True:
        try:
            run_auto_commit_cycle()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in auto-commit cycle: {e}", exc_info=True)
        
        logger.info(f"Sleeping for {INTERVAL_SEC // 60} minutes...")
        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
