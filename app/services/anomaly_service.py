import json
import logging
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus, TransactionType
from app.models.reconciliation import ReconciliationMatch, MatchStatus
from app.models.anomaly import AnomalyRecord, AnomalySeverity, AnomalyCategory, AnomalyStatus
from app.services.audit_service import log_audit

logger = logging.getLogger("finrecon.anomaly_service")

def detect_anomalies(db: Session, user_id: Optional[int] = None) -> List[AnomalyRecord]:
    """
    Transparent rule-based financial anomaly detection service.
    Scans invoices, payments, and allocations for risk indicators, data inconsistencies,
    and compliance discrepancies.
    """
    new_anomalies: List[AnomalyRecord] = []
    today = date.today()

    # Pre-fetch existing active anomaly keys (category + invoice_id + payment_id) to avoid duplicates
    existing_anomalies = db.query(AnomalyRecord).filter(
        AnomalyRecord.status != AnomalyStatus.RESOLVED.value
    ).all()
    existing_keys = set(
        (a.category, a.invoice_id, a.payment_id, a.transaction_reference)
        for a in existing_anomalies
    )

    # 1. DUPLICATE PAYMENTS: Same customer + same amount within 14 days
    payments = db.query(Payment).filter(
        Payment.transaction_type == TransactionType.CREDIT.value
    ).all()
    
    pay_seen: Dict[str, List[Payment]] = {}
    for p in payments:
        if p.customer_name and p.amount:
            norm_name = p.customer_name.strip().lower()
            key = f"{norm_name}_{p.amount:.2f}_{p.currency}"
            pay_seen.setdefault(key, []).append(p)

    for key, p_list in pay_seen.items():
        if len(p_list) > 1:
            for i in range(len(p_list)):
                for j in range(i + 1, len(p_list)):
                    p1, p2 = p_list[i], p_list[j]
                    days_gap = abs((p1.payment_date - p2.payment_date).days)
                    if days_gap <= 14:
                        akey = (AnomalyCategory.DUPLICATE_PAYMENT.value, None, p2.id, p2.transaction_reference)
                        if akey not in existing_keys:
                            record = AnomalyRecord(
                                severity=AnomalySeverity.HIGH.value,
                                category=AnomalyCategory.DUPLICATE_PAYMENT.value,
                                title=f"Potential Duplicate Payment ({p2.currency} {p2.amount:,.2f})",
                                payment_id=p2.id,
                                transaction_reference=p2.transaction_reference,
                                customer_name=p2.customer_name,
                                amount=p2.amount,
                                currency=p2.currency,
                                evidence=json.dumps({
                                    "primary_payment_ref": p1.transaction_reference,
                                    "primary_date": str(p1.payment_date),
                                    "duplicate_candidate_ref": p2.transaction_reference,
                                    "duplicate_date": str(p2.payment_date),
                                    "days_between": days_gap,
                                    "amount": p2.amount,
                                    "currency": p2.currency
                                }),
                                explanation=(
                                    f"Risk indicator: Payment '{p2.transaction_reference}' ({p2.currency} {p2.amount:,.2f}) "
                                    f"shares identical amount and customer '{p2.customer_name}' with payment "
                                    f"'{p1.transaction_reference}' within {days_gap} days. This suggests a potential duplicate batch import or double deposit."
                                ),
                                suggested_action="Verify bank statement to confirm whether this deposit was received twice or if it represents an accidental duplicate entry.",
                                status=AnomalyStatus.PENDING.value
                            )
                            new_anomalies.append(record)
                            existing_keys.add(akey)

    # 2. POTENTIAL DUPLICATE INVOICES: Same customer + same total amount within 14 days
    invoices = db.query(Invoice).all()
    inv_seen: Dict[str, List[Invoice]] = {}
    for inv in invoices:
        if inv.customer_name and inv.total_amount:
            norm_name = inv.customer_name.strip().lower()
            key = f"{norm_name}_{inv.total_amount:.2f}_{inv.currency}"
            inv_seen.setdefault(key, []).append(inv)

    for key, inv_list in inv_seen.items():
        if len(inv_list) > 1:
            for i in range(len(inv_list)):
                for j in range(i + 1, len(inv_list)):
                    i1, i2 = inv_list[i], inv_list[j]
                    days_gap = abs((i1.invoice_date - i2.invoice_date).days)
                    if days_gap <= 14:
                        akey = (AnomalyCategory.DUPLICATE_INVOICE.value, i2.id, None, None)
                        if akey not in existing_keys:
                            record = AnomalyRecord(
                                severity=AnomalySeverity.MEDIUM.value,
                                category=AnomalyCategory.DUPLICATE_INVOICE.value,
                                title=f"Potential Duplicate Invoice ({i2.invoice_number})",
                                invoice_id=i2.id,
                                invoice_number=i2.invoice_number,
                                customer_name=i2.customer_name,
                                amount=i2.total_amount,
                                currency=i2.currency,
                                evidence=json.dumps({
                                    "original_invoice": i1.invoice_number,
                                    "original_date": str(i1.invoice_date),
                                    "suspect_invoice": i2.invoice_number,
                                    "suspect_date": str(i2.invoice_date),
                                    "days_between": days_gap,
                                    "amount": i2.total_amount
                                }),
                                explanation=(
                                    f"Risk indicator: Invoice '{i2.invoice_number}' for customer '{i2.customer_name}' "
                                    f"has the exact same total ({i2.currency} {i2.total_amount:,.2f}) as invoice '{i1.invoice_number}' "
                                    f"issued {days_gap} days apart."
                                ),
                                suggested_action="Review billing records to verify if these are distinct billing cycles or a duplicate bill issuance.",
                                status=AnomalyStatus.PENDING.value
                            )
                            new_anomalies.append(record)
                            existing_keys.add(akey)

    # 3. OVERPAYMENTS: Payments with unallocated amount exceeding matching invoices or over-allocated matches
    matches = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.status.in_([MatchStatus.PROPOSED.value, MatchStatus.APPROVED.value])
    ).all()
    for m in matches:
        if m.allocated_amount > (m.invoice.remaining_amount + m.allocated_amount + 0.01):
            akey = (AnomalyCategory.OVERPAYMENT.value, m.invoice_id, m.payment_id, None)
            if akey not in existing_keys:
                record = AnomalyRecord(
                    severity=AnomalySeverity.HIGH.value,
                    category=AnomalyCategory.OVERPAYMENT.value,
                    title=f"Allocation Overrun on Invoice {m.invoice.invoice_number}",
                    invoice_id=m.invoice_id,
                    payment_id=m.payment_id,
                    invoice_number=m.invoice.invoice_number,
                    transaction_reference=m.payment.transaction_reference,
                    customer_name=m.invoice.customer_name,
                    amount=m.allocated_amount,
                    currency=m.invoice.currency,
                    evidence=json.dumps({
                        "allocated": m.allocated_amount,
                        "invoice_total": m.invoice.total_amount,
                        "invoice_remaining": m.invoice.remaining_amount
                    }),
                    explanation=(
                        f"Data inconsistency: Proposed allocation of {m.invoice.currency} {m.allocated_amount:,.2f} "
                        f"exceeds allowable invoice limits."
                    ),
                    suggested_action="Adjust allocation amount to match remaining balance or record excess as customer credit balance.",
                    status=AnomalyStatus.PENDING.value
                )
                new_anomalies.append(record)
                existing_keys.add(akey)

    # 4. UNMATCHED PAYMENTS: Incoming receipts unallocated for > 15 days
    for p in payments:
        if p.unallocated_amount > 0.01:
            age_days = (today - p.payment_date).days
            if age_days >= 15:
                akey = (AnomalyCategory.UNMATCHED_PAYMENT.value, None, p.id, p.transaction_reference)
                if akey not in existing_keys:
                    severity = AnomalySeverity.HIGH.value if age_days > 45 else AnomalySeverity.MEDIUM.value
                    record = AnomalyRecord(
                        severity=severity,
                        category=AnomalyCategory.UNMATCHED_PAYMENT.value,
                        title=f"Unmatched Bank Deposit ({p.currency} {p.unallocated_amount:,.2f})",
                        payment_id=p.id,
                        transaction_reference=p.transaction_reference,
                        customer_name=p.customer_name,
                        amount=p.unallocated_amount,
                        currency=p.currency,
                        evidence=json.dumps({
                            "payment_date": str(p.payment_date),
                            "age_days": age_days,
                            "unallocated_amount": p.unallocated_amount,
                            "description": p.bank_description
                        }),
                        explanation=(
                            f"Operational alert: Deposit '{p.transaction_reference}' for {p.currency} {p.unallocated_amount:,.2f} "
                            f"received on {p.payment_date} ({age_days} days ago) remains completely or partially unmatched."
                        ),
                        suggested_action="Investigate payer narrative, check for missing invoices, or perform manual split allocation.",
                        status=AnomalyStatus.PENDING.value
                    )
                    new_anomalies.append(record)
                    existing_keys.add(akey)

    # 5. OVERDUE INVOICES: Invoices unpaid for > 30 days past due date
    for inv in invoices:
        if inv.remaining_amount > 0.01 and inv.due_date < today:
            overdue_days = (today - inv.due_date).days
            if overdue_days >= 15:
                akey = (AnomalyCategory.OVERDUE_INVOICE.value, inv.id, None, None)
                if akey not in existing_keys:
                    sev = AnomalySeverity.HIGH.value if overdue_days > 60 else AnomalySeverity.MEDIUM.value
                    record = AnomalyRecord(
                        severity=sev,
                        category=AnomalyCategory.OVERDUE_INVOICE.value,
                        title=f"Severely Overdue Invoice ({inv.invoice_number})",
                        invoice_id=inv.id,
                        invoice_number=inv.invoice_number,
                        customer_name=inv.customer_name,
                        amount=inv.remaining_amount,
                        currency=inv.currency,
                        evidence=json.dumps({
                            "due_date": str(inv.due_date),
                            "days_overdue": overdue_days,
                            "remaining_amount": inv.remaining_amount,
                            "customer": inv.customer_name
                        }),
                        explanation=(
                            f"Credit risk: Invoice '{inv.invoice_number}' for {inv.customer_name} is {overdue_days} days overdue. "
                            f"Outstanding balance: {inv.currency} {inv.remaining_amount:,.2f}."
                        ),
                        suggested_action="Initiate dunning procedure, send payment reminder, or review customer accounts receivable status.",
                        status=AnomalyStatus.PENDING.value
                    )
                    new_anomalies.append(record)
                    existing_keys.add(akey)

    # 6. DATE INCONSISTENCIES: Payment dated far before invoice date or in the future
    for m in matches:
        p_date = m.payment.payment_date
        i_date = m.invoice.invoice_date
        if p_date < (i_date - timedelta(days=60)):
            akey = (AnomalyCategory.DATE_INCONSISTENCY.value, m.invoice_id, m.payment_id, None)
            if akey not in existing_keys:
                record = AnomalyRecord(
                    severity=AnomalySeverity.LOW.value,
                    category=AnomalyCategory.DATE_INCONSISTENCY.value,
                    title=f"Payment Precedes Invoice by > 60 Days",
                    invoice_id=m.invoice_id,
                    payment_id=m.payment_id,
                    invoice_number=m.invoice.invoice_number,
                    transaction_reference=m.payment.transaction_reference,
                    customer_name=m.invoice.customer_name,
                    amount=m.allocated_amount,
                    currency=m.invoice.currency,
                    evidence=json.dumps({
                        "payment_date": str(p_date),
                        "invoice_date": str(i_date),
                        "gap_days": (i_date - p_date).days
                    }),
                    explanation=(
                        f"Audit notice: Payment '{m.payment.transaction_reference}' is dated {p_date}, which is "
                        f"{(i_date - p_date).days} days prior to invoice issue date {i_date}. Verify whether this is an advance retainer or date typo."
                    ),
                    suggested_action="Verify transaction documentation to ensure allocation is properly recognized as an advance payment.",
                    status=AnomalyStatus.PENDING.value
                )
                new_anomalies.append(record)
                existing_keys.add(akey)

    # 7. UNUSUAL PAYMENT AMOUNTS: Outliers (> 3x average invoice amount or negative credits)
    avg_inv_amt = db.query(func.avg(Invoice.total_amount)).scalar() or 5000.0
    for p in payments:
        if p.amount > (avg_inv_amt * 4.0):
            akey = (AnomalyCategory.UNUSUAL_AMOUNT.value, None, p.id, p.transaction_reference)
            if akey not in existing_keys:
                record = AnomalyRecord(
                    severity=AnomalySeverity.MEDIUM.value,
                    category=AnomalyCategory.UNUSUAL_AMOUNT.value,
                    title=f"High-Value Outlier Transaction ({p.currency} {p.amount:,.2f})",
                    payment_id=p.id,
                    transaction_reference=p.transaction_reference,
                    customer_name=p.customer_name,
                    amount=p.amount,
                    currency=p.currency,
                    evidence=json.dumps({
                        "transaction_amount": p.amount,
                        "average_invoice_amount": round(float(avg_inv_amt), 2),
                        "ratio": round(p.amount / float(avg_inv_amt), 1)
                    }),
                    explanation=(
                        f"Compliance notice: Transaction '{p.transaction_reference}' for {p.currency} {p.amount:,.2f} "
                        f"is {round(p.amount / float(avg_inv_amt), 1)}x larger than the average invoice size ({p.currency} {avg_inv_amt:,.2f})."
                    ),
                    suggested_action="Confirm customer purchase order and bank confirmation for high-value settlement.",
                    status=AnomalyStatus.PENDING.value
                )
                new_anomalies.append(record)
                existing_keys.add(akey)

    if new_anomalies:
        db.add_all(new_anomalies)
        db.commit()
        log_audit(
            db,
            action="ANOMALY_SCAN",
            entity_type="SYSTEM",
            entity_id=None,
            description=f"Automated anomaly scan completed. Identified {len(new_anomalies)} risk indicators / discrepancy alerts.",
            details={"anomalies_detected": len(new_anomalies)},
            user_id=user_id
        )
        db.commit()

    return new_anomalies

def resolve_anomaly(
    db: Session,
    anomaly_id: int,
    action: str,  # 'ACKNOWLEDGE' or 'RESOLVE'
    notes: Optional[str] = None,
    user_id: Optional[int] = None
) -> AnomalyRecord:
    """Acknowledge or resolve an identified anomaly alert."""
    record = db.query(AnomalyRecord).filter(AnomalyRecord.id == anomaly_id).first()
    if not record:
        raise ValueError(f"Anomaly record #{anomaly_id} not found.")

    if action == "ACKNOWLEDGE":
        record.status = AnomalyStatus.ACKNOWLEDGED.value
    elif action == "RESOLVE":
        record.status = AnomalyStatus.RESOLVED.value
    else:
        raise ValueError("Action must be either ACKNOWLEDGE or RESOLVE.")

    record.resolution_notes = notes or f"Marked as {action} by user."
    record.resolved_by_user_id = user_id
    record.updated_at = datetime.now(timezone.utc)

    log_audit(
        db,
        action=f"ANOMALY_{action}",
        entity_type="ANOMALY",
        entity_id=record.id,
        description=f"Anomaly #{record.id} ({record.title}) {action.lower()}d. Notes: {record.resolution_notes}",
        details={"anomaly_id": record.id, "status": record.status, "notes": record.resolution_notes},
        user_id=user_id
    )
    db.commit()
    return record

