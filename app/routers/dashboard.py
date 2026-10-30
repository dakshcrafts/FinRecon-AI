from datetime import datetime, date, timedelta
from typing import Dict, Any, List
from collections import defaultdict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path

from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus, TransactionType
from app.models.reconciliation import ReconciliationMatch, MatchStatus, ConfidenceTier
from app.models.audit import AuditLog
from app.models.user import User
from app.services.auth_service import get_current_user
from app.config import settings

router = APIRouter(tags=["Dashboard"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    recent_audits = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(8).all()
    pending_review_count = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.status == MatchStatus.PROPOSED.value
    ).count()

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "current_user": current_user,
        "recent_audits": recent_audits,
        "pending_review_count": pending_review_count,
        "app_name": settings.APP_NAME
    })

@router.get("/api/dashboard/metrics")
def get_dashboard_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    invoices = db.query(Invoice).all()
    # Ensure statuses are updated based on current date
    for inv in invoices:
        inv.update_status()
    db.commit()

    payments = db.query(Payment).all()

    total_inv_count = len(invoices)
    total_inv_amount = sum(inv.total_amount for inv in invoices)
    outstanding_amount = sum(inv.remaining_amount for inv in invoices)

    paid_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.PAID.value)
    partial_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.PARTIALLY_PAID.value)
    unpaid_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.UNPAID.value)
    overdue_count = sum(1 for inv in invoices if inv.status == InvoiceStatus.OVERDUE.value)

    credit_payments = [p for p in payments if p.transaction_type == TransactionType.CREDIT.value]
    total_payments_count = len(credit_payments)
    total_payments_amount = sum(p.amount for p in credit_payments)
    allocated_payments_amount = sum(p.allocated_amount for p in credit_payments)

    unmatched_payments = [p for p in credit_payments if p.unallocated_amount > 0.01]
    unmatched_payments_count = len(unmatched_payments)
    unmatched_payments_amount = sum(p.unallocated_amount for p in unmatched_payments)

    duplicate_candidates = [p for p in payments if p.is_duplicate or p.is_suspicious]
    duplicate_count = len(duplicate_candidates)
    suspicious_count = sum(1 for p in payments if p.is_suspicious)

    recon_rate = round((allocated_payments_amount / total_payments_amount * 100.0), 1) if total_payments_amount > 0 else 0.0

    pending_review_count = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.status == MatchStatus.PROPOSED.value
    ).count()

    from app.models.anomaly import AnomalyRecord, AnomalyStatus
    active_anomalies_count = db.query(AnomalyRecord).filter(
        AnomalyRecord.status != AnomalyStatus.RESOLVED.value
    ).count()

    return {
        "total_invoices_count": total_inv_count,
        "total_invoices_amount": round(total_inv_amount, 2),
        "total_payments_count": total_payments_count,
        "total_payments_amount": round(total_payments_amount, 2),
        "reconciled_amount": round(allocated_payments_amount, 2),
        "paid_count": paid_count,
        "partial_count": partial_count,
        "unpaid_count": unpaid_count,
        "overdue_count": overdue_count,
        "unmatched_payments_count": unmatched_payments_count,
        "unmatched_payments_amount": round(unmatched_payments_amount, 2),
        "duplicate_candidates_count": max(duplicate_count, active_anomalies_count),
        "pending_review_count": pending_review_count,
        "suspicious_count": suspicious_count,
        "outstanding_amount": round(outstanding_amount, 2),
        "reconciliation_rate_percent": recon_rate
    }

@router.get("/api/dashboard/charts")
def get_dashboard_charts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    invoices = db.query(Invoice).all()
    credit_payments = db.query(Payment).filter(Payment.transaction_type == TransactionType.CREDIT.value).all()
    matches = db.query(ReconciliationMatch).all()

    # 1. Monthly Invoice vs Payment
    months_inv = defaultdict(float)
    months_pay = defaultdict(float)

    for inv in invoices:
        m_key = inv.invoice_date.strftime("%Y-%m")
        months_inv[m_key] += inv.total_amount

    for pay in credit_payments:
        m_key = pay.payment_date.strftime("%Y-%m")
        months_pay[m_key] += pay.amount

    all_months = sorted(list(set(list(months_inv.keys()) + list(months_pay.keys()))))
    # Keep up to last 6 months
    all_months = all_months[-6:] if len(all_months) > 6 else all_months

    monthly_labels = [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in all_months]
    monthly_invoices = [round(months_inv[m], 2) for m in all_months]
    monthly_payments = [round(months_pay[m], 2) for m in all_months]

    # 2. Status Distribution
    status_counts = {
        "Paid": sum(1 for i in invoices if i.status == InvoiceStatus.PAID.value),
        "Partially Paid": sum(1 for i in invoices if i.status == InvoiceStatus.PARTIALLY_PAID.value),
        "Unpaid": sum(1 for i in invoices if i.status == InvoiceStatus.UNPAID.value),
        "Overdue": sum(1 for i in invoices if i.status == InvoiceStatus.OVERDUE.value)
    }

    # 3. Top Outstanding by Customer
    cust_outstanding = defaultdict(float)
    for inv in invoices:
        if inv.remaining_amount > 0.01:
            cust_outstanding[inv.customer_name] += inv.remaining_amount

    sorted_cust = sorted(cust_outstanding.items(), key=lambda x: x[1], reverse=True)[:5]
    top_cust_names = [c[0] for c in sorted_cust]
    top_cust_amounts = [round(c[1], 2) for c in sorted_cust]

    # 4. Reconciliation Status Breakdown
    recon_summary = {
        "Approved": sum(1 for m in matches if m.status == MatchStatus.APPROVED.value),
        "Manual Allocated": sum(1 for m in matches if m.status == MatchStatus.MANUAL_ALLOCATED.value),
        "Review Queue": sum(1 for m in matches if m.status == MatchStatus.PROPOSED.value and m.confidence_tier != ConfidenceTier.SUSPICIOUS.value),
        "Suspicious / Alert": sum(1 for m in matches if m.confidence_tier == ConfidenceTier.SUSPICIOUS.value or m.status == MatchStatus.REJECTED.value),
    }

    # 5. Payment Trends (daily / weekly)
    daily_pay = defaultdict(float)
    for pay in sorted(credit_payments, key=lambda x: x.payment_date)[-14:]:
        d_key = pay.payment_date.strftime("%b %d")
        daily_pay[d_key] += pay.amount

    return {
        "monthly_trend": {
            "labels": monthly_labels,
            "invoices": monthly_invoices,
            "payments": monthly_payments
        },
        "status_distribution": {
            "labels": list(status_counts.keys()),
            "counts": list(status_counts.values())
        },
        "top_customers": {
            "labels": top_cust_names,
            "amounts": top_cust_amounts
        },
        "reconciliation_summary": recon_summary,
        "payment_trend": {
            "labels": list(daily_pay.keys()),
            "amounts": [round(v, 2) for v in daily_pay.values()]
        }
    }
