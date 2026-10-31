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
from app.models.payment import Payment, PaymentStatus, TransactionType
from app.models.reconciliation import ReconciliationMatch, MatchStatus
from app.models.user import User
from app.schemas.payment import PaymentCreate, PaymentUpdate, PaymentResponse
from app.services.auth_service import get_current_user
from app.services.payment_parser import parse_bank_statement
from app.services.audit_service import log_audit
from app.config import settings

router = APIRouter(tags=["Payments"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/payments", response_class=HTMLResponse)
def payments_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return templates.TemplateResponse(request=request, name="payments.html", context={
        "current_user": current_user,
        "app_name": settings.APP_NAME
    })

@router.get("/api/payments")
def list_payments(
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    type_filter: Optional[str] = Query(None, alias="type"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Payment)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Payment.transaction_reference.ilike(s),
                Payment.customer_name.ilike(s),
                Payment.bank_description.ilike(s)
            )
        )

    if status_filter and status_filter.upper() != "ALL":
        query = query.filter(Payment.status == status_filter.upper())

    if type_filter and type_filter.upper() != "ALL":
        query = query.filter(Payment.transaction_type == type_filter.upper())

    if start_date:
        query = query.filter(Payment.payment_date >= start_date)
    if end_date:
        query = query.filter(Payment.payment_date <= end_date)

    if min_amount is not None:
        query = query.filter(Payment.amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Payment.amount <= max_amount)

    total_count = query.count()
    payments = query.order_by(Payment.payment_date.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": p.id,
                "transaction_reference": p.transaction_reference,
                "customer_name": p.customer_name,
                "payment_date": p.payment_date.isoformat(),
                "amount": p.amount,
                "allocated_amount": p.allocated_amount,
                "unallocated_amount": p.unallocated_amount,
                "currency": p.currency,
                "payment_method": p.payment_method,
                "bank_description": p.bank_description,
                "transaction_type": p.transaction_type,
                "import_source": p.import_source,
                "is_duplicate": p.is_duplicate,
                "is_suspicious": p.is_suspicious,
                "suspicion_reason": p.suspicion_reason,
                "status": p.status,
                "created_at": p.created_at.isoformat()
            }
            for p in payments
        ]
    }

@router.post("/api/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing = db.query(Payment).filter(Payment.transaction_reference == payload.transaction_reference.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Transaction reference '{payload.transaction_reference}' already exists.")

    is_debit = payload.transaction_type == TransactionType.DEBIT.value
    status_val = PaymentStatus.EXCLUDED.value if is_debit else PaymentStatus.UNMATCHED.value

    payment = Payment(
        transaction_reference=payload.transaction_reference.strip(),
        customer_name=payload.customer_name.strip() if payload.customer_name else None,
        payment_date=payload.payment_date,
        amount=round(payload.amount, 2),
        allocated_amount=0.0,
        unallocated_amount=0.0 if is_debit else round(payload.amount, 2),
        currency=payload.currency.upper(),
        payment_method=payload.payment_method,
        bank_description=payload.bank_description,
        transaction_type=payload.transaction_type,
        import_source="Manual",
        status=status_val
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)

    log_audit(
        db,
        action="PAYMENT_CREATE",
        entity_type="PAYMENT",
        entity_id=payment.id,
        description=f"Created payment {payment.transaction_reference} (${payment.amount:.2f}, {payment.transaction_type}).",
        details={"reference": payment.transaction_reference, "amount": payment.amount, "type": payment.transaction_type},
        user_id=current_user.id
    )
    db.commit()
    return payment

@router.get("/api/payments/{payment_id}")
def get_payment_detail(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")

    matches = db.query(ReconciliationMatch).filter(ReconciliationMatch.payment_id == payment_id).all()

    return {
        "payment": {
            "id": payment.id,
            "transaction_reference": payment.transaction_reference,
            "customer_name": payment.customer_name,
            "payment_date": payment.payment_date.isoformat(),
            "amount": payment.amount,
            "allocated_amount": payment.allocated_amount,
            "unallocated_amount": payment.unallocated_amount,
            "currency": payment.currency,
            "payment_method": payment.payment_method,
            "bank_description": payment.bank_description,
            "transaction_type": payment.transaction_type,
            "is_duplicate": payment.is_duplicate,
            "is_suspicious": payment.is_suspicious,
            "suspicion_reason": payment.suspicion_reason,
            "status": payment.status,
            "created_at": payment.created_at.isoformat()
        },
        "matches": [
            {
                "id": m.id,
                "invoice_id": m.invoice_id,
                "invoice_number": m.invoice.invoice_number if m.invoice else "N/A",
                "customer": m.invoice.customer_name if m.invoice else "N/A",
                "allocated_amount": m.allocated_amount,
                "confidence_score": m.confidence_score,
                "status": m.status,
                "strategy": m.strategy_applied,
                "explanation": m.explanation
            }
            for m in matches
        ]
    }

@router.put("/api/payments/{payment_id}")
def update_payment(
    payment_id: int,
    payload: PaymentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")

    if payload.customer_name is not None:
        payment.customer_name = payload.customer_name.strip()
    if payload.payment_date is not None:
        payment.payment_date = payload.payment_date
    if payload.payment_method is not None:
        payment.payment_method = payload.payment_method
    if payload.bank_description is not None:
        payment.bank_description = payload.bank_description
    if payload.amount is not None:
        new_amt = round(payload.amount, 2)
        if new_amt < payment.allocated_amount:
            raise HTTPException(status_code=400, detail=f"Cannot reduce amount (${new_amt:.2f}) below already allocated amount (${payment.allocated_amount:.2f}).")
        payment.amount = new_amt
        payment.unallocated_amount = round(new_amt - payment.allocated_amount, 2)

    payment.update_status()
    db.commit()

    log_audit(
        db,
        action="PAYMENT_UPDATE",
        entity_type="PAYMENT",
        entity_id=payment.id,
        description=f"Updated payment {payment.transaction_reference}.",
        details={"updated_fields": payload.model_dump(exclude_unset=True)},
        user_id=current_user.id
    )
    db.commit()

    return {"message": "Payment updated successfully", "id": payment.id}

@router.delete("/api/payments/{payment_id}")
def delete_payment(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")

    active_matches = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.payment_id == payment_id,
        ReconciliationMatch.status.in_([MatchStatus.APPROVED.value, MatchStatus.MANUAL_ALLOCATED.value])
    ).count()

    if active_matches > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete payment #{payment.transaction_reference}: has active reconciled allocations. Unmatch them first."
        )

    ref = payment.transaction_reference
    db.delete(payment)
    db.commit()

    log_audit(
        db,
        action="PAYMENT_DELETE",
        entity_type="PAYMENT",
        entity_id=payment_id,
        description=f"Deleted payment {ref}.",
        user_id=current_user.id
    )
    db.commit()

    return {"message": f"Payment {ref} deleted successfully."}

@router.post("/api/payments/import")
async def import_payments_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    filename = file.filename
    content = await file.read()

    if not filename:
        raise HTTPException(status_code=400, detail="Invalid file upload.")

    ext = filename.lower().split('.')[-1]
    if ext not in ["csv", "xlsx", "xls"]:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload CSV or Excel.")

    total, receipts, debits, dups, suspicious, errors = parse_bank_statement(
        content, filename, db, user_id=current_user.id
    )

    return {
        "total_processed": total,
        "receipts_imported": receipts,
        "debits_excluded": debits,
        "duplicates_detected": dups,
        "suspicious_count": suspicious,
        "errors": errors,
        "message": f"Processed {total} transactions: {receipts} incoming receipts imported, {debits} debits excluded, {suspicious} suspicious items flagged."
    }

@router.get("/api/payments/sample-template")
def download_sample_bank_statement_template():
    sample_csv = (
        "transaction_reference,payment_date,amount,currency,payment_method,customer_name,bank_description,transaction_type\n"
        "TXN-2026-901,2026-10-02,12500.00,USD,Wire Transfer,Acme Corporation,INV-2026-001 Enterprise Settlement,CREDIT\n"
        "TXN-2026-902,2026-10-06,4800.00,USD,ACH,Global Logistics,Settlement for telematics inv 2026-002,CREDIT\n"
        "TXN-2026-903,2026-10-07,-35.00,USD,Bank Fee,,Monthly wire service fee,DEBIT\n"
        "TXN-2026-904,2026-10-12,5000.00,USD,Bank Transfer,TechCorp Solutions,Part payment for dev contract,CREDIT\n"
    )
    return StreamingResponse(
        io.StringIO(sample_csv),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_bank_statement.csv"}
    )
