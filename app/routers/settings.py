from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models.reconciliation import ReconciliationSetting
from app.models.user import User
from app.schemas.reconciliation import ReconciliationSettingsUpdate, ReconciliationSettingsResponse
from app.services.auth_service import get_current_user, get_current_admin
from app.services.reconciliation_engine import get_reconciliation_settings
from app.services.audit_service import log_audit
from app.config import settings

router = APIRouter(tags=["Settings"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    setting = get_reconciliation_settings(db)
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "current_user": current_user,
        "setting": setting,
        "app_name": settings.APP_NAME
    })

@router.get("/api/settings/reconciliation", response_model=ReconciliationSettingsResponse)
def get_settings_api(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return get_reconciliation_settings(db)

@router.put("/api/settings/reconciliation", response_model=ReconciliationSettingsResponse)
def update_settings_api(
    payload: ReconciliationSettingsUpdate,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    setting = get_reconciliation_settings(db)
    
    total_weights = payload.weight_invoice_number + payload.weight_customer_name + payload.weight_amount + payload.weight_date_proximity
    if abs(total_weights - 100.0) > 1.0:
        raise HTTPException(
            status_code=400,
            detail=f"Reconciliation weights must sum to 100%. Current sum: {total_weights:.1f}%"
        )

    setting.weight_invoice_number = payload.weight_invoice_number
    setting.weight_customer_name = payload.weight_customer_name
    setting.weight_amount = payload.weight_amount
    setting.weight_date_proximity = payload.weight_date_proximity
    setting.auto_match_threshold = payload.auto_match_threshold
    setting.review_queue_threshold = payload.review_queue_threshold
    setting.ambiguity_margin = payload.ambiguity_margin
    setting.auto_match_enabled = payload.auto_match_enabled
    setting.date_tolerance_days = payload.date_tolerance_days
    setting.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(setting)

    log_audit(
        db,
        action="SETTINGS_UPDATE",
        entity_type="SETTING",
        entity_id=setting.id,
        description="Reconciliation weights, thresholds, and ambiguity margin updated.",
        details=payload.model_dump(),
        user_id=current_admin.id
    )
    db.commit()

    return setting

@router.post("/api/settings/backup")
def create_backup_endpoint(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Trigger safe automated SQLite backup with WAL checkpoint."""
    from app.database import backup_database
    try:
        backup_file = backup_database()
        log_audit(
            db,
            action="DATABASE_BACKUP",
            entity_type="SYSTEM",
            entity_id=None,
            description=f"Manual database backup generated at {backup_file}",
            user_id=current_admin.id
        )
        db.commit()
        return {"success": True, "backup_path": backup_file, "message": "Database backed up successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")

@router.post("/api/settings/reset-demo")
def reset_demo_endpoint(
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Safely reset demo dataset: Backs up the database first, resets seed demo records,
    and runs initial reconciliation to provide a reproducible demo state.
    """
    from app.database import backup_database
    from seed import seed_database
    try:
        # 1. Safe backup
        backup_file = backup_database()

        # 2. Re-seed demo dataset
        seed_database()

        log_audit(
            db,
            action="DEMO_RESET",
            entity_type="SYSTEM",
            entity_id=None,
            description=f"Demo dataset reset to reproducible baseline. Safety backup created at {backup_file}.",
            user_id=current_admin.id
        )
        db.commit()
        return {
            "success": True,
            "message": "Demo dataset restored successfully. Safety backup archived.",
            "backup_path": backup_file
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset demo failed: {str(e)}")
