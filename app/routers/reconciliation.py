import json
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.reconciliation import (
    ReconciliationMatch,
    ReconciliationSetting,
    MatchStatus,
    ConfidenceTier
)
from app.models.user import User
from app.schemas.reconciliation import (
    ReconciliationRunRequest,
    ManualAllocationRequest,
    MatchActionRequest,
    BulkApproveRequest
)
from app.services.auth_service import get_current_user
from app.services.reconciliation_engine import (
    run_reconciliation_pipeline,
    approve_match,
    reject_match,
    manual_allocate,
    unmatch_allocation,
    get_reconciliation_settings
)
from app.services.audit_service import log_audit
from app.config import settings

router = APIRouter(tags=["Reconciliation"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/reconciliation", response_class=HTMLResponse)
def reconciliation_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    setting = get_reconciliation_settings(db)
    return templates.TemplateResponse(request=request, name="reconciliation.html", context={
        "current_user": current_user,
        "setting": setting,
        "app_name": settings.APP_NAME
    })

@router.get("/reconciliation/review", response_class=HTMLResponse)
def review_queue_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    setting = get_reconciliation_settings(db)
    return templates.TemplateResponse(request=request, name="review_queue.html", context={
        "current_user": current_user,
        "setting": setting,
        "app_name": settings.APP_NAME
    })

@router.post("/api/reconciliation/run")
def trigger_reconciliation(
    payload: ReconciliationRunRequest = ReconciliationRunRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        result = run_reconciliation_pipeline(
            db=db,
            auto_approve_high=payload.auto_approve_high,
            re_evaluate_all=payload.re_evaluate_all,
            user_id=current_user.id
        )
        return {
            "success": True,
            "message": f"Reconciliation pipeline executed. Generated {result['matches_generated']} matches.",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconciliation error: {str(e)}")

@router.get("/api/reconciliation/matches")
def list_matches(
    status_filter: Optional[str] = Query(None, alias="status"),
    tier_filter: Optional[str] = Query(None, alias="tier"),
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(ReconciliationMatch)

    if status_filter and status_filter.upper() != "ALL":
        query = query.filter(ReconciliationMatch.status == status_filter.upper())

    if tier_filter and tier_filter.upper() != "ALL":
        query = query.filter(ReconciliationMatch.confidence_tier == tier_filter.upper())

    total_count = query.count()
    matches = query.order_by(
        ReconciliationMatch.status.asc(),
        ReconciliationMatch.confidence_score.desc()
    ).offset((page - 1) * limit).limit(limit).all()

    items = []
    for m in matches:
        inv = m.invoice
        pay = m.payment
        details = {}
        if m.match_details:
            try:
                details = json.loads(m.match_details)
            except Exception:
                details = {"raw": m.match_details}

        items.append({
            "id": m.id,
            "invoice_id": m.invoice_id,
            "payment_id": m.payment_id,
            "allocated_amount": m.allocated_amount,
            "confidence_score": m.confidence_score,
            "confidence_tier": m.confidence_tier,
            "status": m.status,
            "strategy_applied": m.strategy_applied,
            "explanation": m.explanation,
            "match_details": details,
            "created_at": m.created_at.isoformat(),
            "approved_at": m.approved_at.isoformat() if m.approved_at else None,
            "rejected_at": m.rejected_at.isoformat() if m.rejected_at else None,
            "rejection_reason": m.rejection_reason,
            
            # Context fields for UI
            "invoice_number": inv.invoice_number if inv else "N/A",
            "invoice_customer": inv.customer_name if inv else "N/A",
            "invoice_date": inv.invoice_date.isoformat() if inv else "N/A",
            "invoice_due_date": inv.due_date.isoformat() if inv else "N/A",
            "invoice_total": inv.total_amount if inv else 0.0,
            "invoice_remaining": inv.remaining_amount if inv else 0.0,
            "invoice_status": inv.status if inv else "N/A",

            "payment_reference": pay.transaction_reference if pay else "N/A",
            "payment_customer": pay.customer_name if pay else "N/A",
            "payment_date": pay.payment_date.isoformat() if pay else "N/A",
            "payment_amount": pay.amount if pay else 0.0,
            "payment_unallocated": pay.unallocated_amount if pay else 0.0,
            "payment_bank_desc": pay.bank_description if pay else "",
            "payment_is_suspicious": pay.is_suspicious if pay else False,
            "payment_suspicion_reason": pay.suspicion_reason if pay else None,
            "payment_status": pay.status if pay else "N/A"
        })

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": items
    }

@router.post("/api/reconciliation/approve/{match_id}")
def approve_match_endpoint(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        match = approve_match(db, match_id=match_id, user_id=current_user.id)
        return {
            "success": True,
            "message": f"Match #{match_id} approved. Allocated ${match.allocated_amount:.2f}.",
            "match_id": match.id
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to approve match: {str(e)}")

@router.post("/api/reconciliation/reject/{match_id}")
def reject_match_endpoint(
    match_id: int,
    payload: MatchActionRequest = MatchActionRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        match = reject_match(db, match_id=match_id, reason=payload.reason, user_id=current_user.id)
        return {
            "success": True,
            "message": f"Match #{match_id} rejected.",
            "match_id": match.id
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject match: {str(e)}")

@router.post("/api/reconciliation/manual-allocate")
def manual_allocate_endpoint(
    payload: ManualAllocationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        match = manual_allocate(
            db=db,
            invoice_id=payload.invoice_id,
            payment_id=payload.payment_id,
            amount=payload.allocated_amount,
            user_id=current_user.id,
            notes=payload.notes
        )
        return {
            "success": True,
            "message": f"Successfully allocated ${payload.allocated_amount:.2f} manually.",
            "match_id": match.id
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual allocation error: {str(e)}")

@router.post("/api/reconciliation/bulk-approve")
def bulk_approve_endpoint(
    payload: BulkApproveRequest = BulkApproveRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.status == MatchStatus.PROPOSED.value,
        ReconciliationMatch.confidence_tier == ConfidenceTier.HIGH.value
    )
    if payload.match_ids:
        query = query.filter(ReconciliationMatch.id.in_(payload.match_ids))

    candidate_matches = query.all()
    approved_count = 0
    errors = []

    for m in candidate_matches:
        try:
            approve_match(db, m.id, user_id=current_user.id)
            approved_count += 1
        except Exception as e:
            errors.append(f"Match #{m.id}: {str(e)}")

    return {
        "success": True,
        "approved_count": approved_count,
        "failed_count": len(errors),
        "errors": errors,
        "message": f"Bulk approved {approved_count} high-confidence match(es)."
    }

@router.post("/api/reconciliation/unmatch/{match_id}")
def unmatch_endpoint(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        unmatch_allocation(db, match_id=match_id, user_id=current_user.id)
        return {
            "success": True,
            "message": f"Match #{match_id} unallocated successfully. Balances restored."
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unmatch allocation: {str(e)}")
