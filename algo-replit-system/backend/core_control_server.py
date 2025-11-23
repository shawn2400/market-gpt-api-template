"""
ALGO-REPLIT Core Control Server
FastAPI + WebSockets + Redis + Process Manager
Single-user, auto-scaling ready, dormant until expansion
"""

import os
import json
import asyncio
import subprocess
import psutil
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import logging
import hashlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import redis.asyncio as aioredis
from pydantic import BaseModel

# ============================================================
# Configuration
# ============================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ADMIN_TOKEN = os.getenv("ALGO_REPLIT_ADMIN_TOKEN", "admin_default_token_change_me")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", "/home/runner/$REPL_SLUG/workspaces"))
ALGOGPT_ROOT = Path(os.getenv("ALGOGPT_ROOT", "/home/runner/$REPL_SLUG"))
ENABLE_SCALE_MODE = os.getenv("ENABLE_SCALE_MODE", "false").lower() == "true"
SCALE_CPU_THRESHOLD = float(os.getenv("SCALE_CPU_THRESHOLD", "80"))
SCALE_QUEUE_THRESHOLD = int(os.getenv("SCALE_QUEUE_THRESHOLD", "50"))

# Logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)

# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(
    title="ALGO-REPLIT Core Control Server",
    description="Self-hosted development environment for AlgoGPT",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Global State
# ============================================================
redis_client: Optional[aioredis.Redis] = None
active_connections: Dict[str, WebSocket] = {}
process_manager: Dict[str, subprocess.Popen] = {}

# ============================================================
# Models
# ============================================================
class AdminAuth(BaseModel):
    token: str

class ProjectCreate(BaseModel):
    name: str
    template: str = "python"  # python, node, etc.
    description: Optional[str] = None

class ProjectRun(BaseModel):
    project_name: str
    script: str = "run.sh"

class FileOperation(BaseModel):
    path: str
    content: Optional[str] = None
    action: str = "read"  # read, write, delete

class AIAgentRequest(BaseModel):
    query: str
    context: Optional[Dict] = None

# ============================================================
# Authentication
# ============================================================
def verify_admin_token(token: str) -> bool:
    """Verify admin token - single user only"""
    return token == ADMIN_TOKEN

def get_admin_user(auth: AdminAuth) -> str:
    """Dependency: verify admin access"""
    if not verify_admin_token(auth.token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token"
        )
    return "admin"

# ============================================================
# Startup/Shutdown
# ============================================================
@app.on_event("startup")
async def startup_event():
    global redis_client
    try:
        redis_client = await aioredis.from_url(REDIS_URL)
        await redis_client.ping()
        logger.info("✅ Redis connected")
    except Exception as e:
        logger.warning(f"⚠️ Redis unavailable: {e}. Running without caching.")
        redis_client = None
    
    # Initialize workspaces directory
    WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info(f"✅ Workspaces root: {WORKSPACES_ROOT}")

@app.on_event("shutdown")
async def shutdown_event():
    global redis_client
    if redis_client:
        await redis_client.close()
    # Stop all running processes
    for proc_name, proc in process_manager.items():
        try:
            proc.terminate()
            logger.info(f"Stopped {proc_name}")
        except:
            pass

# ============================================================
# Health & Status
# ============================================================
@app.get("/health")
async def health_check():
    """System health check with resource monitoring"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Check if auto-scaling should activate
    should_scale = (
        (cpu_percent > SCALE_CPU_THRESHOLD or 
         memory.percent > 85) 
        and not ENABLE_SCALE_MODE
    )
    
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "resources": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_available_mb": memory.available // (1024 * 1024),
            "disk_percent": disk.percent,
        },
        "scale_mode_enabled": ENABLE_SCALE_MODE,
        "should_activate_scale_mode": should_scale,
        "redis_connected": redis_client is not None,
        "running_processes": list(process_manager.keys()),
    }

@app.get("/status")
async def system_status():
    """Full system status with audit log"""
    redis_info = None
    if redis_client:
        try:
            redis_info = await redis_client.info()
        except:
            pass
    
    return {
        "system": "ALGO-REPLIT Core Control Server v1.0",
        "mode": "SCALE_MODE" if ENABLE_SCALE_MODE else "SINGLE_USER",
        "workspaces_root": str(WORKSPACES_ROOT),
        "algogpt_root": str(ALGOGPT_ROOT),
        "active_connections": len(active_connections),
        "running_services": len(process_manager),
        "redis_available": redis_client is not None,
        "timestamp": datetime.utcnow().isoformat(),
    }

# ============================================================
# Project Management
# ============================================================
@app.post("/projects/create")
async def create_project(req: ProjectCreate, token: str):
    """Create new project workspace"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    project_dir = WORKSPACES_ROOT / req.name
    
    if project_dir.exists():
        raise HTTPException(status_code=400, detail=f"Project {req.name} already exists")
    
    # Create project structure
    project_dir.mkdir(parents=True)
    (project_dir / "src").mkdir()
    (project_dir / "tests").mkdir()
    (project_dir / "logs").mkdir()
    
    # Create template files
    if req.template == "python":
        (project_dir / "requirements.txt").write_text("# Add dependencies here\n")
        (project_dir / "run.sh").write_text("#!/bin/bash\npython src/main.py\n")
        (project_dir / "src" / "main.py").write_text('print("Hello from AlgoGPT workspace")\n')
    
    # Create metadata
    metadata = {
        "name": req.name,
        "template": req.template,
        "description": req.description or "",
        "created_at": datetime.utcnow().isoformat(),
        "last_modified": datetime.utcnow().isoformat(),
    }
    (project_dir / "project.json").write_text(json.dumps(metadata, indent=2))
    
    # Log to Redis
    if redis_client:
        await redis_client.lpush(
            "audit:project_create",
            json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "create_project",
                "project": req.name,
                "template": req.template,
            })
        )
    
    logger.info(f"✅ Created project: {req.name}")
    return {
        "status": "success",
        "project": req.name,
        "path": str(project_dir),
    }

@app.get("/projects")
async def list_projects(token: str):
    """List all projects"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    projects = []
    for project_dir in WORKSPACES_ROOT.iterdir():
        if project_dir.is_dir():
            metadata_file = project_dir / "project.json"
            if metadata_file.exists():
                metadata = json.loads(metadata_file.read_text())
                projects.append(metadata)
    
    return {"projects": projects}

# ============================================================
# File Operations (Sandboxed)
# ============================================================
@app.post("/files/read")
async def read_file(req: FileOperation, token: str):
    """Read file from workspace"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Security: ensure path is within workspaces or algogpt root
    file_path = Path(req.path).resolve()
    
    if not (str(file_path).startswith(str(WORKSPACES_ROOT)) or
            str(file_path).startswith(str(ALGOGPT_ROOT))):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        content = file_path.read_text()
        return {
            "path": str(file_path),
            "content": content,
            "size": len(content),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/files/write")
async def write_file(req: FileOperation, token: str):
    """Write file to workspace"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    file_path = Path(req.path).resolve()
    
    if not (str(file_path).startswith(str(WORKSPACES_ROOT)) or
            str(file_path).startswith(str(ALGOGPT_ROOT))):
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(req.content or "")
        
        # Log to Redis
        if redis_client:
            await redis_client.lpush(
                "audit:file_write",
                json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    "path": str(file_path),
                    "size": len(req.content or ""),
                })
            )
        
        logger.info(f"✅ Wrote file: {file_path}")
        return {"status": "success", "path": str(file_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Process Manager
# ============================================================
@app.post("/services/start")
async def start_service(req: ProjectRun, token: str):
    """Start a project service"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    project_dir = WORKSPACES_ROOT / req.project_name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    script_path = project_dir / req.script
    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"Script {req.script} not found")
    
    try:
        # Make script executable
        os.chmod(script_path, 0o755)
        
        # Start process
        proc = subprocess.Popen(
            [f"bash", str(script_path)],
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        service_id = f"{req.project_name}_{uuid.uuid4().hex[:8]}"
        process_manager[service_id] = proc
        
        logger.info(f"✅ Started service: {service_id}")
        return {
            "status": "started",
            "service_id": service_id,
            "project": req.project_name,
            "pid": proc.pid,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/services/stop")
async def stop_service(service_id: str, token: str):
    """Stop a running service"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if service_id not in process_manager:
        raise HTTPException(status_code=404, detail="Service not found")
    
    try:
        proc = process_manager[service_id]
        proc.terminate()
        proc.wait(timeout=5)
        del process_manager[service_id]
        
        logger.info(f"✅ Stopped service: {service_id}")
        return {"status": "stopped", "service_id": service_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/services")
async def list_services(token: str):
    """List all running services"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    services = []
    for service_id, proc in process_manager.items():
        services.append({
            "service_id": service_id,
            "pid": proc.pid,
            "running": proc.poll() is None,
        })
    
    return {"services": services}

# ============================================================
# WebSocket Logs Streaming
# ============================================================
@app.websocket("/ws/logs/{service_id}")
async def websocket_logs(websocket: WebSocket, service_id: str):
    """Stream logs from running service"""
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    active_connections[connection_id] = websocket
    
    try:
        if service_id not in process_manager:
            await websocket.send_json({"error": "Service not found"})
            return
        
        proc = process_manager[service_id]
        
        # Stream logs
        while proc.poll() is None:
            try:
                if proc.stdout:
                    line = proc.stdout.readline()
                    if line:
                        await websocket.send_json({
                            "type": "log",
                            "content": line.strip(),
                            "timestamp": datetime.utcnow().isoformat(),
                        })
            except (asyncio.TimeoutError, AttributeError):
                pass
            
            await asyncio.sleep(0.1)
        
        # Send final exit code
        await websocket.send_json({
            "type": "exit",
            "code": proc.returncode,
        })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    finally:
        del active_connections[connection_id]

# ============================================================
# AlgoGPT Integration
# ============================================================
@app.get("/algogpt/files")
async def get_algogpt_files(token: str):
    """List AlgoGPT project files"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    py_files = list(ALGOGPT_ROOT.rglob("*.py"))
    json_files = list(ALGOGPT_ROOT.rglob("*.json"))
    yaml_files = list(ALGOGPT_ROOT.rglob("*.yaml"))
    
    return {
        "python_files": len(py_files),
        "json_files": len(json_files),
        "yaml_files": len(yaml_files),
        "total_files": len(py_files) + len(json_files) + len(yaml_files),
    }

@app.post("/algogpt/run_tests")
async def run_algogpt_tests(token: str):
    """Run AlgoGPT unit tests"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-v"],
            cwd=str(ALGOGPT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        return {
            "status": "completed",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/algogpt/apply_patch")
async def apply_algogpt_patch(req: Dict[str, Any], token: str):
    """Apply patch to AlgoGPT codebase (requires confirmation in logs)"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Log patch request
    patch_log = {
        "timestamp": datetime.utcnow().isoformat(),
        "status": "pending_admin_review",
        "patch": req.get("patch", ""),
        "description": req.get("description", ""),
    }
    
    if redis_client:
        await redis_client.lpush(
            "audit:patch_requests",
            json.dumps(patch_log)
        )
    
    return {
        "status": "pending",
        "message": "Patch logged. Requires admin confirmation.",
        "log_id": patch_log["timestamp"],
    }

# ============================================================
# Backup & Recovery
# ============================================================
@app.post("/backup/create")
async def create_backup(token: str):
    """Create backup of workspaces"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    import shutil
    
    backup_dir = WORKSPACES_ROOT.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().isoformat().replace(":", "-")
    backup_path = backup_dir / f"backup_{timestamp}"
    
    try:
        shutil.copytree(WORKSPACES_ROOT, backup_path)
        
        if redis_client:
            await redis_client.lpush(
                "audit:backups",
                json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": "backup_created",
                    "path": str(backup_path),
                })
            )
        
        logger.info(f"✅ Backup created: {backup_path}")
        return {"status": "success", "backup_path": str(backup_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/backup/list")
async def list_backups(token: str):
    """List available backups"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    backup_dir = WORKSPACES_ROOT.parent / "backups"
    if not backup_dir.exists():
        return {"backups": []}
    
    backups = []
    for backup in sorted(backup_dir.iterdir(), reverse=True):
        if backup.is_dir():
            backups.append({
                "name": backup.name,
                "path": str(backup),
                "created": backup.stat().st_mtime,
            })
    
    return {"backups": backups[:7]}  # Keep 7 days

# ============================================================
# Audit Log
# ============================================================
@app.get("/audit/logs")
async def get_audit_logs(action: Optional[str] = None, token: str = ""):
    """Get audit logs"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if not redis_client:
        return {"logs": [], "message": "Redis unavailable"}
    
    try:
        if action:
            logs = await redis_client.lrange(f"audit:{action}", 0, 100)
        else:
            logs = await redis_client.lrange("audit:all", 0, 100)
        
        return {
            "logs": [json.loads(log) if isinstance(log, str) else log for log in logs]
        }
    except Exception as e:
        return {"logs": [], "error": str(e)}

# ============================================================
# Emergency Safety
# ============================================================
freeze_switch_enabled = False

@app.post("/emergency/freeze")
async def emergency_freeze(token: str):
    """Freeze all processes immediately"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    global freeze_switch_enabled
    freeze_switch_enabled = True
    
    # Stop all services
    for service_id in list(process_manager.keys()):
        try:
            proc = process_manager[service_id]
            proc.terminate()
        except:
            pass
    
    logger.warning("🔴 EMERGENCY FREEZE ACTIVATED")
    
    if redis_client:
        await redis_client.lpush(
            "audit:emergency",
            json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "emergency_freeze",
            })
        )
    
    return {"status": "frozen", "message": "All services stopped"}

@app.post("/emergency/unfreeze")
async def emergency_unfreeze(token: str):
    """Unfreeze system"""
    if not verify_admin_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    global freeze_switch_enabled
    freeze_switch_enabled = False
    
    logger.info("✅ System unfrozen")
    return {"status": "unfrozen"}

# ============================================================
# Root endpoint
# ============================================================
@app.get("/")
async def root():
    return {
        "message": "ALGO-REPLIT Core Control Server",
        "version": "1.0.0",
        "mode": "SINGLE_USER",
        "docs": "/docs",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("CONTROL_SERVER_PORT", "8001")),
        log_level=LOG_LEVEL.lower(),
    )
