#!/usr/bin/env python3
# utils/github_auto_commit.py
"""
GitHub Auto-Commit - Autonomous Code Updates
============================================
Enables AI brains to commit improvements directly to GitHub
without human intervention.

Uses GitHub API to:
- Create commits with AI improvements
- Push to a dedicated branch (ai-improvements)
- Optionally create PRs for review
"""
import os
import logging
import httpx
from typing import Dict, Any, Optional
from pathlib import Path
import base64

logger = logging.getLogger("algogpt.github_auto_commit")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()  # Format: "owner/repo"
GITHUB_BRANCH = os.getenv("GITHUB_AI_BRANCH", "ai-improvements")
GITHUB_ENABLED = os.getenv("GITHUB_AUTO_COMMIT_ENABLE", "1") == "1" and GITHUB_TOKEN and GITHUB_REPO

AUTO_CREATE_PR = os.getenv("GITHUB_AUTO_CREATE_PR", "0") == "1"


async def commit_ai_improvements(commit_message: str, files_to_commit: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Commit AI improvements to GitHub
    
    Args:
        commit_message: Commit message describing changes
        files_to_commit: Dict of {filepath: content} to commit. If None, commits config/trading_params.json
    
    Returns:
        {"ok": True, "commit_sha": "...", "branch": "..."} or {"ok": False, "error": "..."}
    """
    if not GITHUB_ENABLED:
        logger.warning("GitHub auto-commit disabled. Set GITHUB_TOKEN and GITHUB_REPO.")
        return {"ok": False, "error": "github_disabled"}
    
    try:
        if files_to_commit is None:
            config_file = Path("config/trading_params.json")
            if not config_file.exists():
                return {"ok": False, "error": "no_config_file"}
            
            with open(config_file, 'r') as f:
                content = f.read()
            
            files_to_commit = {"config/trading_params.json": content}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            
            owner, repo = GITHUB_REPO.split("/")
            base_url = f"https://api.github.com/repos/{owner}/{repo}"
            
            main_branch_resp = await client.get(
                f"{base_url}/git/ref/heads/main",
                headers=headers
            )
            
            if main_branch_resp.status_code != 200:
                logger.error(f"Failed to get main branch: {main_branch_resp.status_code}")
                return {"ok": False, "error": "failed_to_get_main_branch"}
            
            main_sha = main_branch_resp.json()["object"]["sha"]
            
            ai_branch_resp = await client.get(
                f"{base_url}/git/ref/heads/{GITHUB_BRANCH}",
                headers=headers
            )
            
            if ai_branch_resp.status_code == 404:
                create_branch_resp = await client.post(
                    f"{base_url}/git/refs",
                    headers=headers,
                    json={
                        "ref": f"refs/heads/{GITHUB_BRANCH}",
                        "sha": main_sha
                    }
                )
                if create_branch_resp.status_code != 201:
                    logger.error(f"Failed to create AI branch: {create_branch_resp.status_code}")
                    return {"ok": False, "error": "failed_to_create_branch"}
                
                branch_sha = main_sha
                logger.info(f"Created new branch: {GITHUB_BRANCH}")
            else:
                branch_sha = ai_branch_resp.json()["object"]["sha"]
            
            tree_items = []
            
            for filepath, content in files_to_commit.items():
                blob_resp = await client.post(
                    f"{base_url}/git/blobs",
                    headers=headers,
                    json={
                        "content": content,
                        "encoding": "utf-8"
                    }
                )
                
                if blob_resp.status_code != 201:
                    logger.error(f"Failed to create blob for {filepath}: {blob_resp.status_code}")
                    continue
                
                blob_sha = blob_resp.json()["sha"]
                
                tree_items.append({
                    "path": filepath,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha
                })
            
            if not tree_items:
                return {"ok": False, "error": "no_blobs_created"}
            
            tree_resp = await client.post(
                f"{base_url}/git/trees",
                headers=headers,
                json={
                    "base_tree": branch_sha,
                    "tree": tree_items
                }
            )
            
            if tree_resp.status_code != 201:
                logger.error(f"Failed to create tree: {tree_resp.status_code}")
                return {"ok": False, "error": "failed_to_create_tree"}
            
            tree_sha = tree_resp.json()["sha"]
            
            commit_resp = await client.post(
                f"{base_url}/git/commits",
                headers=headers,
                json={
                    "message": commit_message,
                    "tree": tree_sha,
                    "parents": [branch_sha]
                }
            )
            
            if commit_resp.status_code != 201:
                logger.error(f"Failed to create commit: {commit_resp.status_code}")
                return {"ok": False, "error": "failed_to_create_commit"}
            
            commit_sha = commit_resp.json()["sha"]
            
            update_ref_resp = await client.patch(
                f"{base_url}/git/refs/heads/{GITHUB_BRANCH}",
                headers=headers,
                json={
                    "sha": commit_sha,
                    "force": False
                }
            )
            
            if update_ref_resp.status_code != 200:
                logger.error(f"Failed to update branch ref: {update_ref_resp.status_code}")
                return {"ok": False, "error": "failed_to_update_ref"}
            
            logger.info(f"✅ Commit successful: {commit_sha[:8]} on {GITHUB_BRANCH}")
            
            result = {
                "ok": True,
                "commit_sha": commit_sha,
                "branch": GITHUB_BRANCH,
                "url": f"https://github.com/{GITHUB_REPO}/commit/{commit_sha}"
            }
            
            if AUTO_CREATE_PR:
                pr_result = await _create_pull_request(client, headers, base_url, commit_message)
                result["pr"] = pr_result
            
            return result
    
    except Exception as e:
        logger.error(f"GitHub commit failed: {e}")
        return {"ok": False, "error": str(e)}


async def _create_pull_request(client: httpx.AsyncClient, headers: Dict[str, str], 
                               base_url: str, title: str) -> Dict[str, Any]:
    """Create a pull request for AI improvements"""
    try:
        pr_resp = await client.post(
            f"{base_url}/pulls",
            headers=headers,
            json={
                "title": title.split("\n")[0],
                "body": title,
                "head": GITHUB_BRANCH,
                "base": "main"
            }
        )
        
        if pr_resp.status_code == 201:
            pr_data = pr_resp.json()
            logger.info(f"✅ Pull request created: {pr_data['html_url']}")
            return {
                "ok": True,
                "pr_number": pr_data["number"],
                "pr_url": pr_data["html_url"]
            }
        else:
            logger.warning(f"Failed to create PR: {pr_resp.status_code} - {pr_resp.text}")
            return {"ok": False, "error": "failed_to_create_pr"}
    
    except Exception as e:
        logger.error(f"PR creation failed: {e}")
        return {"ok": False, "error": str(e)}
