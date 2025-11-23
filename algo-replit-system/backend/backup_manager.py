"""
ALGO-REPLIT Backup & Recovery System
Automatic nightly backups, 7-day retention, one-click restore
"""

import os
import shutil
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import asyncio
import gzip
import tarfile

logger = logging.getLogger(__name__)

WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", "/home/runner/$REPL_SLUG/workspaces"))
BACKUPS_ROOT = WORKSPACES_ROOT.parent / "backups"
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "7"))

class BackupManager:
    def __init__(self):
        self.backups_root = BACKUPS_ROOT
        self.backups_root.mkdir(parents=True, exist_ok=True)
    
    def create_backup(self, compress: bool = True) -> Dict[str, Any]:
        """Create backup of workspaces"""
        timestamp = datetime.utcnow().isoformat().replace(":", "-")
        backup_name = f"backup_{timestamp}"
        backup_path = self.backups_root / backup_name
        
        try:
            # Create backup directory
            backup_path.mkdir(parents=True, exist_ok=True)
            
            # Copy workspaces
            logger.info(f"Creating backup: {backup_path}")
            for workspace in WORKSPACES_ROOT.iterdir():
                if workspace.is_dir():
                    dest = backup_path / workspace.name
                    shutil.copytree(workspace, dest)
            
            # Compress if needed
            if compress:
                tar_path = backup_path.with_suffix('.tar.gz')
                with tarfile.open(tar_path, "w:gz") as tar:
                    tar.add(backup_path, arcname=backup_name)
                
                shutil.rmtree(backup_path)
                backup_path = tar_path
            
            # Create metadata
            metadata = {
                "timestamp": datetime.utcnow().isoformat(),
                "name": backup_name,
                "compressed": compress,
                "path": str(backup_path),
                "size_bytes": backup_path.stat().st_size,
            }
            
            logger.info(f"✅ Backup created: {backup_path}")
            return {
                "status": "success",
                "backup": metadata,
            }
        except Exception as e:
            logger.error(f"Backup creation failed: {e}")
            return {"status": "error", "message": str(e)}
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups"""
        backups = []
        
        if not self.backups_root.exists():
            return backups
        
        for backup in sorted(self.backups_root.iterdir(), reverse=True):
            try:
                stat = backup.stat()
                backups.append({
                    "name": backup.name,
                    "path": str(backup),
                    "created": stat.st_mtime,
                    "size_bytes": stat.st_size,
                    "is_compressed": backup.name.endswith('.tar.gz'),
                })
            except:
                pass
        
        return backups
    
    def restore_backup(self, backup_name: str, safe_mode: bool = True) -> Dict[str, Any]:
        """Restore backup (replaces current workspaces)"""
        backup_path = self.backups_root / backup_name
        
        if not backup_path.exists():
            return {"status": "error", "message": "Backup not found"}
        
        try:
            # Create temp restore location
            temp_restore = self.backups_root / f"restore_{datetime.utcnow().isoformat().replace(':', '-')}"
            
            if backup_path.name.endswith('.tar.gz'):
                # Extract compressed backup
                with tarfile.open(backup_path, "r:gz") as tar:
                    tar.extractall(temp_restore)
                
                # Get extracted directory
                extracted_dir = list(temp_restore.iterdir())[0]
            else:
                # Copy uncompressed backup
                shutil.copytree(backup_path, temp_restore / backup_path.name)
                extracted_dir = temp_restore / backup_path.name
            
            # Backup current state if safe mode
            safe_backup = None
            if safe_mode:
                safe_backup = self.create_backup(compress=True)
                logger.info(f"Current state backed up: {safe_backup}")
            
            # Replace workspaces
            if WORKSPACES_ROOT.exists():
                shutil.rmtree(WORKSPACES_ROOT)
            
            shutil.copytree(extracted_dir, WORKSPACES_ROOT)
            
            # Cleanup
            shutil.rmtree(temp_restore)
            
            logger.info(f"✅ Backup restored: {backup_name}")
            return {
                "status": "success",
                "message": f"Restored from {backup_name}",
                "safe_backup": safe_backup,
            }
        except Exception as e:
            logger.error(f"Backup restore failed: {e}")
            return {"status": "error", "message": str(e)}
    
    def cleanup_old_backups(self) -> Dict[str, Any]:
        """Remove backups older than retention period"""
        cutoff_time = datetime.utcnow() - timedelta(days=BACKUP_RETENTION_DAYS)
        cutoff_timestamp = cutoff_time.timestamp()
        
        removed = []
        
        for backup in self.backups_root.iterdir():
            try:
                stat = backup.stat()
                if stat.st_mtime < cutoff_timestamp:
                    if backup.is_dir():
                        shutil.rmtree(backup)
                    else:
                        backup.unlink()
                    
                    removed.append(backup.name)
                    logger.info(f"Removed old backup: {backup.name}")
            except:
                pass
        
        return {
            "status": "success",
            "removed_count": len(removed),
            "removed": removed,
        }
    
    def export_backup(self, backup_name: str, format: str = "zip") -> Dict[str, Any]:
        """Export backup as zip or tar.gz"""
        backup_path = self.backups_root / backup_name
        
        if not backup_path.exists():
            return {"status": "error", "message": "Backup not found"}
        
        try:
            if format == "zip":
                export_path = backup_path.with_suffix('.zip')
                shutil.make_archive(str(export_path.with_suffix('')), 'zip', backup_path)
            else:  # tar.gz
                export_path = backup_path.with_suffix('.tar.gz')
                with tarfile.open(export_path, "w:gz") as tar:
                    tar.add(backup_path, arcname=backup_name)
            
            return {
                "status": "success",
                "export_path": str(export_path),
                "size_bytes": export_path.stat().st_size,
            }
        except Exception as e:
            logger.error(f"Backup export failed: {e}")
            return {"status": "error", "message": str(e)}
    
    async def run_scheduled_backup(self):
        """Run scheduled backup (hourly, daily, etc.)"""
        while True:
            try:
                # Backup every 24 hours
                await asyncio.sleep(86400)
                
                result = self.create_backup(compress=True)
                logger.info(f"Scheduled backup completed: {result}")
                
                # Cleanup old backups
                cleanup = self.cleanup_old_backups()
                logger.info(f"Cleanup: {cleanup}")
            except Exception as e:
                logger.error(f"Scheduled backup failed: {e}")

# Singleton instance
backup_manager = BackupManager()

async def get_backup_manager() -> BackupManager:
    """Dependency: get backup manager"""
    return backup_manager
