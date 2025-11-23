import os
from pathlib import Path
from fastapi import HTTPException

def list_files(root_workspace: str):
    """List all files in workspace"""
    files = []
    for root, _, filenames in os.walk(root_workspace):
        for f in filenames:
            path = os.path.join(root, f)
            rel_path = os.path.relpath(path, root_workspace)
            files.append(rel_path)
    return files

def read_file(path: str, root_workspace: str):
    """Read file from workspace"""
    full_path = os.path.normpath(os.path.join(root_workspace, path))
    
    # Security check
    if not full_path.startswith(os.path.normpath(root_workspace)):
        raise HTTPException(403, "Access denied")
    
    if not os.path.exists(full_path):
        raise HTTPException(404, "File not found")
    
    with open(full_path, "r") as f:
        return f.read()

def write_file(path: str, content: str, root_workspace: str):
    """Write file to workspace"""
    full_path = os.path.normpath(os.path.join(root_workspace, path))
    
    # Security check
    if not full_path.startswith(os.path.normpath(root_workspace)):
        raise HTTPException(403, "Access denied")
    
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(content)
    
    return {"status": "ok", "path": path}

def delete_file(path: str, root_workspace: str):
    """Delete file from workspace"""
    full_path = os.path.normpath(os.path.join(root_workspace, path))
    
    # Security check
    if not full_path.startswith(os.path.normpath(root_workspace)):
        raise HTTPException(403, "Access denied")
    
    if os.path.exists(full_path):
        os.remove(full_path)
        return {"status": "ok"}
    
    raise HTTPException(404, "File not found")
