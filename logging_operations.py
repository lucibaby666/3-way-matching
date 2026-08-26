# logging_operations.py
import json
from datetime import datetime
from pathlib import Path

# Import logging
from app.logging_config import setup_logging, AuditSeverity, get_logger
from database_operations import insert_audit_to_db


# Setup logger
logger = setup_logging(name="ThreeWayMatching", log_dir="./logs")


def log_and_insert(event_type, action, severity=AuditSeverity.INFO, status="SUCCESS", 
                   resource="", resource_type="", error=None, metadata=None, user="system"):
    """Log and insert into database simultaneously"""
    
    # Create audit entry
    audit_entry = {
        "audit_id": f"HITL-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "event_type": event_type,
        "severity": severity.value if hasattr(severity, 'value') else str(severity),
        "user": user,
        "action": action,
        "resource": resource,
        "resource_type": resource_type,
        "status": status,
        "error": error,
        "metadata": metadata or {},
        "timestamp": datetime.now().isoformat()
    }
    
    # Log to file
    if severity == AuditSeverity.INFO:
        logger.info(f"{event_type} - {action} - {status}")
    elif severity == AuditSeverity.WARNING:
        logger.warning(f"{event_type} - {action} - {status}")
    elif severity in [AuditSeverity.HIGH, AuditSeverity.CRITICAL]:
        logger.error(f"{event_type} - {action} - {status}")
    
    # Also log with the logger's log method
    logger.log(
        event_type=event_type,
        action=action,
        severity=severity,
        status=status,
        resource=resource,
        resource_type=resource_type,
        error=error,
        metadata=metadata
    )
    
    # Insert to database immediately
    try:
        insert_audit_to_db(audit_entry)
    except Exception as e:
        print(f"⚠️ Could not insert audit to DB: {e}")
    
    # Return audit_entry and statistics update info for tracking
    return audit_entry