import logging
from datetime import date, datetime
from typing import Dict, List, Any, Optional
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models.invoice import Invoice, InvoiceStatus
from app.models.reconciliation import ReconciliationMatch, MatchStatus

logger = logging.getLogger("finrecon.outstanding_service")

def get_aging_category(due_date: date, today: Optional[date] = None) -> Tuple_Aging:
    """Classify overdue days into standard financial aging buckets."""
    if today is None:
        today = date.today()
    days_overdue = (today - due_date).days
    if days_overdue <= 0:
        return "NOT_DUE", 0, "Current (Not Due)"
    elif 1 <= days_overdue <= 30:
        return "1_30_DAYS", days_overdue, "1–30 Days Overdue"
    elif 31 <= days_overdue <= 60:
        return "31_60_DAYS", days_overdue, "31–60 Days Overdue"
    elif 61 <= days_overdue <= 90:
        return "61_90_DAYS", days_overdue, "61–90 Days Overdue"
    else:
        return "OVER_90_DAYS", days_overdue, ">90 Days Overdue"

def get_outstanding_receivables(
    db: Session,
    customer_name: Optional[str] = None,
    aging_category: Optional[str] = None,
    currency: Optional[str] = None,
    status_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compute outstanding accounts receivable intelligence directly from database records
    and approved allocation ledger to ensure mathematical reconciliation.
    """
    today = date.today()

    query = db.query(Invoice).filter(Invoice.remaining_amount > 0.005)

    if customer_name:
        query = query.filter(Invoice.customer_name.ilike(f"%{customer_name.strip()}%"))
    if currency:
        query = query.filter(Invoice.currency == currency.strip().upper())
    if status_filter:
        query = query.filter(Invoice.status == status_filter.strip().upper())

    invoices = query.order_by(Invoice.due_date.asc()).all()

    # Calculate actual allocations for each invoice from approved matches
    invoice_ids = [inv.id for inv in invoices]
    allocations_map: Dict[int, float] = {}
    if invoice_ids:
        alloc_results = db.query(
            ReconciliationMatch.invoice_id,
            func.sum(ReconciliationMatch.allocated_amount)
        ).filter(
            ReconciliationMatch.invoice_id.in_(invoice_ids),
            ReconciliationMatch.status.in_([MatchStatus.APPROVED.value, MatchStatus.MANUAL_ALLOCATED.value])
        ).group_by(ReconciliationMatch.invoice_id).all()
        for i_id, total_alloc in alloc_results:
            allocations_map[i_id] = round(float(total_alloc or 0.0), 2)

    items: List[Dict[str, Any]] = []
    bucket_totals = {
        "NOT_DUE": 0.0,
        "1_30_DAYS": 0.0,
        "31_60_DAYS": 0.0,
        "61_90_DAYS": 0.0,
        "OVER_90_DAYS": 0.0
    }
    bucket_counts = {
        "NOT_DUE": 0,
        "1_30_DAYS": 0,
        "31_60_DAYS": 0,
        "61_90_DAYS": 0,
        "OVER_90_DAYS": 0
    }

    total_receivable = 0.0
    total_invoiced = 0.0
    total_collected = 0.0
    customer_summaries: Dict[str, Dict[str, Any]] = {}

    for inv in invoices:
        bucket_code, days_overdue, bucket_label = get_aging_category(inv.due_date, today)

        # Apply aging category filter if provided
        if aging_category and aging_category != "ALL" and bucket_code != aging_category:
            continue

        verified_paid = allocations_map.get(inv.id, inv.paid_amount)
        verified_remaining = round(max(0.0, inv.total_amount - verified_paid), 2)

        total_invoiced = round(total_invoiced + inv.total_amount, 2)
        total_collected = round(total_collected + verified_paid, 2)
        total_receivable = round(total_receivable + verified_remaining, 2)

        bucket_totals[bucket_code] = round(bucket_totals[bucket_code] + verified_remaining, 2)
        bucket_counts[bucket_code] += 1

        # Customer aggregation
        cname = inv.customer_name
        if cname not in customer_summaries:
            customer_summaries[cname] = {
                "customer_name": cname,
                "total_invoiced": 0.0,
                "total_paid": 0.0,
                "total_outstanding": 0.0,
                "invoice_count": 0,
                "max_days_overdue": 0
            }
        customer_summaries[cname]["total_invoiced"] = round(customer_summaries[cname]["total_invoiced"] + inv.total_amount, 2)
        customer_summaries[cname]["total_paid"] = round(customer_summaries[cname]["total_paid"] + verified_paid, 2)
        customer_summaries[cname]["total_outstanding"] = round(customer_summaries[cname]["total_outstanding"] + verified_remaining, 2)
        customer_summaries[cname]["invoice_count"] += 1
        if days_overdue > customer_summaries[cname]["max_days_overdue"]:
            customer_summaries[cname]["max_days_overdue"] = days_overdue

        items.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "customer_name": inv.customer_name,
            "customer_email": inv.customer_email,
            "invoice_date": str(inv.invoice_date),
            "due_date": str(inv.due_date),
            "days_overdue": days_overdue,
            "aging_category": bucket_code,
            "aging_label": bucket_label,
            "total_amount": inv.total_amount,
            "paid_amount": verified_paid,
            "remaining_amount": verified_remaining,
            "currency": inv.currency,
            "status": inv.status,
            "description": inv.description
        })

    # Sort customers by highest outstanding balance
    sorted_customers = sorted(customer_summaries.values(), key=lambda c: c["total_outstanding"], reverse=True)

    return {
        "items": items,
        "total_records": len(items),
        "total_invoiced": total_invoiced,
        "total_collected": total_collected,
        "total_outstanding": total_receivable,
        "bucket_totals": bucket_totals,
        "bucket_counts": bucket_counts,
        "customers_summary": sorted_customers
    }

