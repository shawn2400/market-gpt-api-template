# utils/audit.py
# -*- coding: utf-8 -*-
"""
בס"ד
Audit Logging System
Logs all critical actions to database for compliance and debugging
"""
from __future__ import annotations

import logging
import json
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger("algogpt.audit")


async def log_action(
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    user_id: Optional[str] = None,
    changes: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    success: bool = True,
    error: Optional[str] = None
) -> bool:
    """
    Log an action to the audit log
    
    Args:
        action: Action performed (e.g., "validation_start", "breaker_pause", "trade_execute")
        entity_type: Type of entity (e.g., "validation", "breaker", "trade", "order")
        entity_id: Unique identifier of the entity
        user_id: User who performed the action
        changes: Dictionary of changes made (before/after values)
        ip_address: IP address of requester
        success: Whether the action succeeded
        error: Error message if action failed
        
    Returns:
        bool: True if logged successfully
    """
    try:
        from utils.db import _conn, _is_postgres, DB_URL
        
        timestamp = datetime.utcnow()
        changes_json = json.dumps(changes) if changes else None
        
        with _conn() as con:
            if con is None:
                logger.warning("Database not enabled, audit log skipped")
                return False
            
            cur = con.cursor()
            
            if _is_postgres(DB_URL):
                # PostgreSQL with JSONB
                cur.execute("""
                    INSERT INTO audit_log 
                    (timestamp, user_id, action, entity_type, entity_id, changes, ip_address, success, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    timestamp,
                    user_id,
                    action,
                    entity_type,
                    entity_id,
                    changes_json,
                    ip_address,
                    success,
                    error
                ))
            else:
                # SQLite with TEXT JSON
                cur.execute("""
                    INSERT INTO audit_log 
                    (timestamp, user_id, action, entity_type, entity_id, changes, ip_address, success, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp.timestamp(),
                    user_id,
                    action,
                    entity_type,
                    entity_id,
                    changes_json,
                    ip_address,
                    1 if success else 0,
                    error
                ))
            
            logger.info(
                f"Audit log: {action} on {entity_type}:{entity_id} "
                f"by {user_id or 'system'} - {'success' if success else 'failed'}"
            )
            return True
            
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}", exc_info=True)
        return False


async def get_audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 100
) -> list:
    """
    Retrieve audit logs with optional filters
    
    Args:
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        user_id: Filter by user ID
        limit: Maximum number of logs to return
        
    Returns:
        List of audit log entries
    """
    try:
        from utils.db import _conn, _is_postgres, DB_URL
        
        with _conn() as con:
            if con is None:
                return []
            
            cur = con.cursor()
            
            # Build query with filters
            conditions = []
            params = []
            
            if entity_type:
                conditions.append("entity_type = ?")
                params.append(entity_type)
            if entity_id:
                conditions.append("entity_id = ?")
                params.append(entity_id)
            if user_id:
                conditions.append("user_id = ?")
                params.append(user_id)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            if _is_postgres(DB_URL):
                query = f"""
                    SELECT id, timestamp, user_id, action, entity_type, entity_id, 
                           changes, ip_address, success, error
                    FROM audit_log
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                params.append(limit)
                cur.execute(query, params)
            else:
                query = f"""
                    SELECT id, timestamp, user_id, action, entity_type, entity_id, 
                           changes, ip_address, success, error
                    FROM audit_log
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                params.append(limit)
                cur.execute(query, params)
            
            rows = cur.fetchall()
            
            logs = []
            for row in rows:
                log_entry = {
                    "id": row[0],
                    "timestamp": row[1],
                    "user_id": row[2],
                    "action": row[3],
                    "entity_type": row[4],
                    "entity_id": row[5],
                    "changes": json.loads(row[6]) if row[6] else None,
                    "ip_address": row[7],
                    "success": bool(row[8]) if isinstance(row[8], int) else row[8],
                    "error": row[9]
                }
                logs.append(log_entry)
            
            return logs
            
    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {e}", exc_info=True)
        return []
