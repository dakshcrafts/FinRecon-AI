from typing import Optional
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.services.auth_service import get_current_user
from app.config import settings

router = APIRouter(tags=["Audit Logs"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/audit-logs", response_class=HTMLResponse)
def audit_logs_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return templates.TemplateResponse(request=request, name="audit_logs.html", context={
        "current_user": current_user,
        "app_name": settings.APP_NAME
    })

@router.get("/api/audit-logs")
def list_audit_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(AuditLog)

    if action and action.upper() != "ALL":
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))

    if entity_type and entity_type.upper() != "ALL":
        query = query.filter(AuditLog.entity_type == entity_type.upper())

    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "user_email": log.user.email if log.user else "System / Automated",
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "description": log.description,
                "details": log.details,
                "created_at": log.created_at.isoformat()
            }
            for log in logs
        ]
    }
