import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.report_generator import generate_excel_report, generate_pdf_report
from app.services.audit_service import log_audit
from app.config import settings

router = APIRouter(tags=["Reports"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return templates.TemplateResponse(request=request, name="reports.html", context={
        "current_user": current_user,
        "app_name": settings.APP_NAME
    })

@router.get("/api/reports/excel")
def download_excel_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    excel_bytes = generate_excel_report(db)
    filename = f"Gripher_Ledger_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    log_audit(
        db,
        action="REPORT_EXPORT_EXCEL",
        entity_type="SYSTEM",
        entity_id=None,
        description=f"Exported full reconciliation Excel report ({filename}).",
        user_id=current_user.id
    )
    db.commit()

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/api/reports/pdf/{report_type}")
def download_pdf_report(
    report_type: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    valid_types = ["summary", "unmatched", "outstanding", "suspicious", "discrepancies", "audit"]
    clean_type = report_type.lower().strip()
    if clean_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid report type '{report_type}'. Must be one of: {', '.join(valid_types)}"
        )

    pdf_bytes = generate_pdf_report(db, report_type=clean_type)
    filename = f"Gripher_{clean_type.capitalize()}_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    log_audit(
        db,
        action=f"REPORT_EXPORT_PDF_{clean_type.upper()}",
        entity_type="SYSTEM",
        entity_id=None,
        description=f"Exported {clean_type} PDF report ({filename}).",
        user_id=current_user.id
    )
    db.commit()

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
