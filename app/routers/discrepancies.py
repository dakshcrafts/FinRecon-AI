import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.anomaly import AnomalyRecord, AnomalyStatus, AnomalySeverity, AnomalyCategory
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.anomaly_service import detect_anomalies, resolve_anomaly
from app.config import settings

logger = logging.getLogger("finrecon.routers.discrepancies")

router = APIRouter(tags=["Discrepancies and Alerts"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/discrepancies", response_class=HTMLResponse)
def discrepancies_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    total_anomalies = db.query(AnomalyRecord).count()
    pending_count = db.query(AnomalyRecord).filter(AnomalyRecord.status == AnomalyStatus.PENDING.value).count()
    high_count = db.query(AnomalyRecord).filter(
        AnomalyRecord.severity == AnomalySeverity.HIGH.value,
        AnomalyRecord.status != AnomalyStatus.RESOLVED.value
    ).count()

    return templates.TemplateResponse(request=request, name="discrepancies.html", context={
        "current_user": current_user,
        "app_name": settings.APP_NAME,
        "total_anomalies": total_anomalies,
        "pending_count": pending_count,
        "high_count": high_count
    })

@router.get("/api/discrepancies")
def get_discrepancies_list(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(AnomalyRecord)
    if status and status != "ALL":
        query = query.filter(AnomalyRecord.status == status.upper())
    if severity and severity != "ALL":
        query = query.filter(AnomalyRecord.severity == severity.upper())
    if category and category != "ALL":
        query = query.filter(AnomalyRecord.category == category.upper())

    records = query.order_by(AnomalyRecord.created_at.desc()).all()

    return {
        "count": len(records),
        "items": [
            {
                "id": r.id,
                "severity": r.severity,
                "category": r.category,
                "title": r.title,
                "invoice_number": r.invoice_number,
                "transaction_reference": r.transaction_reference,
                "customer_name": r.customer_name,
                "amount": r.amount,
                "currency": r.currency,
                "evidence": r.evidence,
                "explanation": r.explanation,
                "suggested_action": r.suggested_action,
                "status": r.status,
                "resolution_notes": r.resolution_notes,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M UTC") if r.created_at else None
            }
            for r in records
        ]
    }

@router.post("/api/discrepancies/scan")
def trigger_anomaly_scan(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Trigger transparent rule-based discrepancy and anomaly scan across all financial data."""
    try:
        new_records = detect_anomalies(db, user_id=current_user.id)
        return {
            "success": True,
            "message": f"Scan completed successfully. Found {len(new_records)} new discrepancy/risk indicators.",
            "new_count": len(new_records)
        }
    except Exception as e:
        logger.error(f"Error during anomaly scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/discrepancies/{anomaly_id}/action")
def update_anomaly_status(
    anomaly_id: int,
    action: str = Form(...),
    notes: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        updated = resolve_anomaly(db, anomaly_id, action=action.upper(), notes=notes, user_id=current_user.id)
        return {
            "success": True,
            "id": updated.id,
            "status": updated.status,
            "notes": updated.resolution_notes
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error updating anomaly {anomaly_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

