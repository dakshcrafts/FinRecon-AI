import io
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pathlib import Path

from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.reconciliation import ReconciliationMatch, MatchStatus
from app.models.user import User
from app.schemas.invoice import InvoiceCreate, InvoiceUpdate, InvoiceResponse, InvoiceImportResult
from app.services.auth_service import get_current_user
from app.services.invoice_parser import parse_invoices_tabular, parse_invoice_pdf
from app.services.audit_service import log_audit
from app.config import settings

router = APIRouter(tags=["Invoices"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/invoices", response_class=HTMLResponse)
def invoices_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return templates.TemplateResponse(request=request, name="invoices.html", context={
        "current_user": current_user,
        "app_name": settings.APP_NAME
    })

@router.get("/api/invoices")
def list_invoices(
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Invoice)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Invoice.invoice_number.ilike(s),
                Invoice.customer_name.ilike(s),
                Invoice.description.ilike(s)
            )
        )

    if status_filter and status_filter.upper() != "ALL":
        query = query.filter(Invoice.status == status_filter.upper())

    if start_date:
        query = query.filter(Invoice.invoice_date >= start_date)
    if end_date:
        query = query.filter(Invoice.invoice_date <= end_date)

    total_count = query.count()
    invoices = query.order_by(Invoice.invoice_date.desc()).offset((page - 1) * limit).limit(limit).all()

    # Refresh status based on today
    for inv in invoices:
        inv.update_status()
    db.commit()

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "customer_name": inv.customer_name,
                "customer_email": inv.customer_email,
                "invoice_date": inv.invoice_date.isoformat(),
                "due_date": inv.due_date.isoformat(),
                "total_amount": inv.total_amount,
                "paid_amount": inv.paid_amount,
                "remaining_amount": inv.remaining_amount,
                "tax_amount": inv.tax_amount,
                "currency": inv.currency,
                "description": inv.description,
                "status": inv.status,
                "import_source": inv.import_source,
                "import_filename": inv.import_filename,
                "created_at": inv.created_at.isoformat()
            }
            for inv in invoices
        ]
    }

@router.post("/api/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_invoice(
    payload: InvoiceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing = db.query(Invoice).filter(Invoice.invoice_number == payload.invoice_number.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Invoice number '{payload.invoice_number}' already exists.")

    invoice = Invoice(
        invoice_number=payload.invoice_number.strip(),
        customer_name=payload.customer_name.strip(),
        customer_email=payload.customer_email.strip() if payload.customer_email else None,
        invoice_date=payload.invoice_date,
        due_date=payload.due_date,
        total_amount=round(payload.total_amount, 2),
        paid_amount=0.0,
        remaining_amount=round(payload.total_amount, 2),
        tax_amount=round(payload.tax_amount, 2),
        currency=payload.currency.upper(),
        description=payload.description,
        import_source="Manual"
    )
    invoice.update_status()

    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    log_audit(
        db,
        action="INVOICE_CREATE",
        entity_type="INVOICE",
        entity_id=invoice.id,
        description=f"Created invoice {invoice.invoice_number} for {invoice.customer_name} (${invoice.total_amount:.2f}).",
        details={"invoice_number": invoice.invoice_number, "total": invoice.total_amount},
        user_id=current_user.id
    )
    db.commit()
    return invoice

@router.get("/api/invoices/{invoice_id}")
def get_invoice_detail(
    invoice_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    matches = db.query(ReconciliationMatch).filter(ReconciliationMatch.invoice_id == invoice_id).all()

    return {
        "invoice": {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "customer_name": invoice.customer_name,
            "customer_email": invoice.customer_email,
            "invoice_date": invoice.invoice_date.isoformat(),
            "due_date": invoice.due_date.isoformat(),
            "total_amount": invoice.total_amount,
            "paid_amount": invoice.paid_amount,
            "remaining_amount": invoice.remaining_amount,
            "tax_amount": invoice.tax_amount,
            "currency": invoice.currency,
            "description": invoice.description,
            "status": invoice.status,
            "import_source": invoice.import_source,
            "import_filename": invoice.import_filename,
            "created_at": invoice.created_at.isoformat()
        },
        "matches": [
            {
                "id": m.id,
                "payment_id": m.payment_id,
                "payment_ref": m.payment.transaction_reference if m.payment else "N/A",
                "payment_date": m.payment.payment_date.isoformat() if m.payment else "N/A",
                "allocated_amount": m.allocated_amount,
                "confidence_score": m.confidence_score,
                "status": m.status,
                "strategy": m.strategy_applied,
                "explanation": m.explanation
            }
            for m in matches
        ]
    }

@router.put("/api/invoices/{invoice_id}")
def update_invoice(
    invoice_id: int,
    payload: InvoiceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    if payload.customer_name is not None:
        invoice.customer_name = payload.customer_name.strip()
    if payload.customer_email is not None:
        invoice.customer_email = payload.customer_email.strip()
    if payload.invoice_date is not None:
        invoice.invoice_date = payload.invoice_date
    if payload.due_date is not None:
        invoice.due_date = payload.due_date
    if payload.description is not None:
        invoice.description = payload.description
    if payload.total_amount is not None:
        old_total = invoice.total_amount
        new_total = round(payload.total_amount, 2)
        if new_total < invoice.paid_amount:
            raise HTTPException(status_code=400, detail=f"Cannot reduce total (${new_total:.2f}) below already paid amount (${invoice.paid_amount:.2f}).")
        invoice.total_amount = new_total
        invoice.remaining_amount = round(new_total - invoice.paid_amount, 2)
    if payload.tax_amount is not None:
        invoice.tax_amount = round(payload.tax_amount, 2)

    invoice.update_status()
    db.commit()

    log_audit(
        db,
        action="INVOICE_UPDATE",
        entity_type="INVOICE",
        entity_id=invoice.id,
        description=f"Updated invoice {invoice.invoice_number}.",
        details={"updated_fields": payload.model_dump(exclude_unset=True)},
        user_id=current_user.id
    )
    db.commit()

    return {"message": "Invoice updated successfully", "id": invoice.id}

@router.delete("/api/invoices/{invoice_id}")
def delete_invoice(
    invoice_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    active_matches = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.invoice_id == invoice_id,
        ReconciliationMatch.status.in_([MatchStatus.APPROVED.value, MatchStatus.MANUAL_ALLOCATED.value])
    ).count()

    if active_matches > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete invoice #{invoice.invoice_number}: has active reconciled payments. Unmatch the allocations first."
        )

    inv_num = invoice.invoice_number
    db.delete(invoice)
    db.commit()

    log_audit(
        db,
        action="INVOICE_DELETE",
        entity_type="INVOICE",
        entity_id=invoice_id,
        description=f"Deleted invoice {inv_num}.",
        user_id=current_user.id
    )
    db.commit()

    return {"message": f"Invoice {inv_num} deleted successfully."}

@router.post("/api/invoices/import")
async def import_invoices_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    filename = file.filename
    content = await file.read()

    if not filename:
        raise HTTPException(status_code=400, detail="Invalid file upload.")

    ext = filename.lower().split('.')[-1]
    if ext not in ["csv", "xlsx", "xls", "pdf"]:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload CSV, Excel (.xlsx/.xls), or PDF.")

    if ext == "pdf":
        imported, skipped, duplicates, errors = parse_invoice_pdf(content, filename, db, user_id=current_user.id)
    else:
        imported, skipped, duplicates, errors = parse_invoices_tabular(content, filename, db, user_id=current_user.id)

    return {
        "imported_count": imported,
        "skipped_count": skipped,
        "duplicates": duplicates,
        "errors": errors,
        "message": f"Successfully imported {imported} invoice(s). Skipped {skipped} duplicate(s)."
    }

@router.get("/api/invoices/sample-template")
def download_sample_invoices_template():
    sample_csv = (
        "invoice_number,customer_name,customer_email,invoice_date,due_date,total_amount,tax_amount,currency,description\n"
        "INV-2026-001,Acme Corporation,billing@acme.com,2026-10-01,2026-10-31,12500.00,1250.00,USD,Enterprise Cloud Infrastructure Services\n"
        "INV-2026-002,Global Logistics Inc,ap@globallogistics.com,2026-10-05,2026-11-04,4800.00,400.00,USD,Fleet Tracking Telematics Subscription\n"
        "INV-2026-003,TechCorp Solutions,finance@techcorp.io,2026-10-10,2026-11-09,9200.00,800.00,USD,Dedicated Software Development Q3\n"
    )
    return StreamingResponse(
        io.StringIO(sample_csv),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_invoices_template.csv"}
    )
