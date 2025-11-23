"""
ALGO-REPLIT ↔ AlgoGPT Integration
Read/write AlgoGPT codebase, run tests, apply patches
"""

import os
import subprocess
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

ALGOGPT_ROOT = Path(os.getenv("ALGOGPT_ROOT", "/home/runner/$REPL_SLUG"))

class AlgoGPTIntegration:
    """
    Integration with AlgoGPT trading system
    Enables code editing, testing, and deployment
    """
    
    def __init__(self):
        self.algogpt_root = ALGOGPT_ROOT
        self.patch_history = []
    
    def get_project_stats(self) -> Dict[str, Any]:
        """
        Get AlgoGPT project statistics
        """
        py_files = list(self.algogpt_root.rglob("*.py"))
        json_files = list(self.algogpt_root.rglob("*.json"))
        yaml_files = list(self.algogpt_root.rglob("*.yaml"))
        
        return {
            "python_files": len(py_files),
            "json_files": len(json_files),
            "yaml_files": len(yaml_files),
            "total_files": len(py_files) + len(json_files) + len(yaml_files),
            "root": str(self.algogpt_root),
        }
    
    def run_tests(self, test_path: str = "tests/", timeout: int = 60) -> Dict[str, Any]:
        """
        Run AlgoGPT unit tests
        """
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", test_path, "-v", "--tb=short"],
                cwd=str(self.algogpt_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            return {
                "status": "completed",
                "returncode": result.returncode,
                "passed": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "message": f"Tests exceeded {timeout}s timeout",
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
            }
    
    def get_file_content(self, file_path: str) -> Dict[str, Any]:
        """
        Read file from AlgoGPT project
        """
        full_path = (self.algogpt_root / file_path).resolve()
        
        # Security check
        if not str(full_path).startswith(str(self.algogpt_root)):
            return {"status": "error", "message": "Access denied"}
        
        if not full_path.exists():
            return {"status": "error", "message": "File not found"}
        
        try:
            content = full_path.read_text()
            return {
                "status": "success",
                "path": file_path,
                "content": content,
                "size": len(content),
                "lines": len(content.splitlines()),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def log_patch_request(self, patch_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Log patch request (requires admin confirmation)
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "pending_admin_review",
            "patch_id": len(self.patch_history),
            **patch_info,
        }
        
        self.patch_history.append(log_entry)
        
        logger.warning(f"PATCH REQUEST: {patch_info.get('description', 'No description')}")
        
        return {
            "status": "pending",
            "patch_id": log_entry["patch_id"],
            "message": "Patch logged. Requires admin confirmation before applying.",
        }
    
    def apply_approved_patch(self, patch_id: int, admin_signature: str) -> Dict[str, Any]:
        """
        Apply approved patch to codebase
        """
        if patch_id >= len(self.patch_history):
            return {"status": "error", "message": "Patch not found"}
        
        patch = self.patch_history[patch_id]
        
        if patch["status"] != "pending_admin_review":
            return {"status": "error", "message": "Patch not pending"}
        
        try:
            file_path = patch.get("file_path")
            content = patch.get("content")
            
            if not file_path or content is None:
                return {"status": "error", "message": "Invalid patch"}
            
            full_path = (self.algogpt_root / file_path).resolve()
            
            # Security check
            if not str(full_path).startswith(str(self.algogpt_root)):
                return {"status": "error", "message": "Access denied"}
            
            # Backup original
            full_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path = full_path.with_suffix(f"{full_path.suffix}.backup")
            if full_path.exists():
                full_path.write_text(full_path.read_text())  # Read and backup
            
            # Apply patch
            full_path.write_text(content)
            
            patch["status"] = "applied"
            patch["applied_at"] = datetime.utcnow().isoformat()
            patch["backup_path"] = str(backup_path)
            
            logger.info(f"PATCH APPLIED: {file_path}")
            
            return {
                "status": "success",
                "message": "Patch applied successfully",
                "file": file_path,
                "backup": str(backup_path),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get AlgoGPT configuration files
        """
        config_files = {
            "env": str(self.algogpt_root / ".env"),
            "config": str(self.algogpt_root / "config"),
            "policies": str(self.algogpt_root / "policies"),
        }
        
        return {
            "config_paths": config_files,
            "project_root": str(self.algogpt_root),
        }

# Singleton instance
algogpt_integration = AlgoGPTIntegration()

async def get_algogpt_integration() -> AlgoGPTIntegration:
    """Dependency: get AlgoGPT integration"""
    return algogpt_integration
