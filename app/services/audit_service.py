import json
import logging
from typing import Optional, Any
from sqlalchemy.orm import Session
from app.models.audit import AuditLog

logger = logging.getLogger("finrecon.audit")

def log_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Optional[Any],
    description: str,
    details: Optional[Any] = None,
    user_id: Optional[int] = None
) -> AuditLog:
    """Record an audit trail event in the database."""
    try:
        details_str = None
        if details is not None:
            if isinstance(details, (dict, list)):
                details_str = json.dumps(details, default=str)
            else:
                details_str = str(details)

        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            description=description,
            details=details_str
        )
        db.add(audit_entry)
        # Flush so the audit entry gets an ID, caller can commit in transaction
        db.flush()
        return audit_entry
    except Exception as e:
        logger.error(f"Failed to log audit entry: {e}")
        return None
