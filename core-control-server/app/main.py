from fastapi import FastAPI, Request, WebSocket, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import asyncio

from .settings import settings
from .auth import verify_admin
from .file_manager import list_files, read_file, write_file, delete_file
from .exec_manager import run_command
from .websocket_manager import terminal_session
from .ai_router import AIRouter
from .audit import audit

# Initialize
app = FastAPI(title="ALGO-REPLIT Core Control Server", version="1.0.0")
ai_router = AIRouter()
admin_token = settings.ADMIN_TOKEN

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure workspace exists
os.makedirs(settings.ROOT_WORKSPACE, exist_ok=True)

# ============================================================
# Health & Status
# ============================================================

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "mode": "single-user"
    }

# ============================================================
# Files API
# ============================================================

@app.get("/api/files")
async def api_list_files(request: Request):
    """List all files"""
    try:
        verify_admin(request, admin_token)
        audit(settings.AUDIT_LOG, "LIST_FILES")
        return {"files": list_files(settings.ROOT_WORKSPACE)}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/files/{path:path}")
async def api_read_file(path: str, request: Request):
    """Read file"""
    try:
        verify_admin(request, admin_token)
        audit(settings.AUDIT_LOG, f"READ_FILE {path}")
        content = read_file(path, settings.ROOT_WORKSPACE)
        return {"path": path, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/files/{path:path}")
async def api_write_file(path: str, request: Request):
    """Write file"""
    try:
        verify_admin(request, admin_token)
        body = await request.json()
        content = body.get("content", "")
        audit(settings.AUDIT_LOG, f"WRITE_FILE {path}")
        result = write_file(path, content, settings.ROOT_WORKSPACE)
        return result
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

@app.delete("/api/files/{path:path}")
async def api_delete_file(path: str, request: Request):
    """Delete file"""
    try:
        verify_admin(request, admin_token)
        audit(settings.AUDIT_LOG, f"DELETE_FILE {path}")
        result = delete_file(path, settings.ROOT_WORKSPACE)
        return result
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# Command Execution
# ============================================================

@app.post("/api/run")
async def api_run_command(request: Request):
    """Run shell command"""
    try:
        verify_admin(request, admin_token)
        body = await request.json()
        cmd = body.get("cmd", "")
        audit(settings.AUDIT_LOG, f"RUN_CMD {cmd}")
        result = run_command(cmd)
        return result
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# Terminal WebSocket
# ============================================================

@app.websocket("/ws/terminal")
async def websocket_endpoint(websocket: WebSocket):
    """Interactive terminal"""
    # Get token from query
    token = websocket.query_params.get("token")
    
    if token != admin_token:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    
    audit(settings.AUDIT_LOG, "WS_TERMINAL_START")
    await terminal_session(websocket)
    audit(settings.AUDIT_LOG, "WS_TERMINAL_END")

# ============================================================
# AI API
# ============================================================

@app.post("/api/ai")
async def api_ask_ai(request: Request):
    """Ask AI question"""
    try:
        verify_admin(request, admin_token)
        body = await request.json()
        prompt = body.get("prompt", "")
        audit(settings.AUDIT_LOG, f"AI_REQUEST {prompt[:50]}")
        response = ai_router.ask(prompt)
        return {"response": response}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# Audit Log
# ============================================================

@app.get("/api/audit")
async def api_get_audit(request: Request):
    """Get audit log"""
    try:
        verify_admin(request, admin_token)
        
        if not os.path.exists(settings.AUDIT_LOG):
            return {"logs": []}
        
        with open(settings.AUDIT_LOG, "r") as f:
            logs = f.readlines()[-100:]  # Last 100 entries
        
        return {"logs": [log.strip() for log in logs]}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# Projects
# ============================================================

@app.post("/api/projects/create")
async def api_create_project(request: Request):
    """Create new project"""
    try:
        verify_admin(request, admin_token)
        body = await request.json()
        project_name = body.get("name", "untitled")
        template = body.get("template", "python")
        
        project_path = os.path.join(settings.ROOT_WORKSPACE, project_name)
        os.makedirs(project_path, exist_ok=True)
        
        # Create template files
        if template == "python":
            write_file(f"{project_name}/main.py", "print('Hello AlgoGPT')\n", settings.ROOT_WORKSPACE)
            write_file(f"{project_name}/requirements.txt", "", settings.ROOT_WORKSPACE)
            write_file(f"{project_name}/run.sh", "#!/bin/bash\npython main.py\n", settings.ROOT_WORKSPACE)
        
        audit(settings.AUDIT_LOG, f"CREATE_PROJECT {project_name}")
        return {"status": "ok", "project": project_name}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/projects")
async def api_list_projects(request: Request):
    """List all projects"""
    try:
        verify_admin(request, admin_token)
        projects = []
        
        for item in os.listdir(settings.ROOT_WORKSPACE):
            item_path = os.path.join(settings.ROOT_WORKSPACE, item)
            if os.path.isdir(item_path) and not item.startswith("_"):
                projects.append(item)
        
        return {"projects": projects}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# Root
# ============================================================

@app.get("/")
async def root():
    return {
        "name": "ALGO-REPLIT Core Control Server",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
