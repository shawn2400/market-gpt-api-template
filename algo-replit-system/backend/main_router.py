"""
ALGO-REPLIT Main Router Integration
Combines all modules into unified API
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import os

from .core_control_server import app as core_app
from .ollama_ai_agent import get_ollama_agent, CodeGenRequest, CodeModifyRequest
from .backup_manager import get_backup_manager
from .scale_manager import get_scale_manager
from .safety_manager import get_safety_manager
from .algogpt_integration import get_algogpt_integration

router = APIRouter(prefix="/api", tags=["integrated"])

# ============================================================
# AI Integration Routes
# ============================================================

@router.post("/ai/generate")
async def ai_generate(req: CodeGenRequest, token: str, agent=Depends(get_ollama_agent)):
    """Generate code using local AI"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await agent.generate_code(req)
    return result

@router.post("/ai/modify")
async def ai_modify(req, token: str, agent=Depends(get_ollama_agent)):
    """Modify code using local AI"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await agent.modify_code(req)
    return result

@router.post("/ai/explain-error")
async def ai_explain_error(req, token: str, agent=Depends(get_ollama_agent)):
    """Explain error using AI"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await agent.explain_error(req)
    return result

@router.post("/ai/chat")
async def ai_chat(req: dict, token: str, agent=Depends(get_ollama_agent)):
    """Chat with AI"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await agent.chat(req.get("query", ""), req.get("context"))
    return result

# ============================================================
# Scale Manager Routes
# ============================================================

@router.get("/scale/status")
async def scale_status(token: str, manager=Depends(get_scale_manager)):
    """Get scaling status"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return manager.get_status()

@router.post("/scale/enable")
async def scale_enable(token: str, manager=Depends(get_scale_manager)):
    """Enable scale mode"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return await manager.enable_scale_mode()

@router.post("/scale/disable")
async def scale_disable(token: str, manager=Depends(get_scale_manager)):
    """Disable scale mode"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return await manager.disable_scale_mode()

# ============================================================
# Safety Manager Routes
# ============================================================

@router.get("/safety/status")
async def safety_status(token: str, manager=Depends(get_safety_manager)):
    """Get safety status"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return manager.get_status()

@router.get("/safety/audit-log")
async def safety_audit_log(token: str, limit: int = 100, manager=Depends(get_safety_manager)):
    """Get audit log"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return {"logs": manager.get_audit_log(limit)}

# ============================================================
# Backup Routes
# ============================================================

@router.post("/backup/create")
async def backup_create(token: str, manager=Depends(get_backup_manager)):
    """Create backup"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return manager.create_backup(compress=True)

@router.get("/backup/list")
async def backup_list(token: str, manager=Depends(get_backup_manager)):
    """List backups"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return {"backups": manager.list_backups()}

@router.post("/backup/restore")
async def backup_restore(backup_name: str, token: str, manager=Depends(get_backup_manager)):
    """Restore from backup"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return manager.restore_backup(backup_name, safe_mode=True)

# ============================================================
# AlgoGPT Integration Routes
# ============================================================

@router.get("/algogpt/stats")
async def algogpt_stats(token: str, integration=Depends(get_algogpt_integration)):
    """Get AlgoGPT project statistics"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return integration.get_project_stats()

@router.post("/algogpt/run-tests")
async def algogpt_run_tests(token: str, test_path: str = "tests/", integration=Depends(get_algogpt_integration)):
    """Run AlgoGPT tests"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return integration.run_tests(test_path)

@router.get("/algogpt/file")
async def algogpt_get_file(path: str, token: str, integration=Depends(get_algogpt_integration)):
    """Get AlgoGPT file"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return integration.get_file_content(path)

@router.post("/algogpt/patch-request")
async def algogpt_patch_request(patch: dict, token: str, integration=Depends(get_algogpt_integration)):
    """Request code patch"""
    if token != os.getenv("ALGO_REPLIT_ADMIN_TOKEN", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return integration.log_patch_request(patch)

# Attach to main app
core_app.include_router(router)
