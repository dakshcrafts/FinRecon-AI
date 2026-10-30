import json
import logging
from datetime import datetime, date, timezone
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus, TransactionType
from app.models.reconciliation import (
    ReconciliationMatch,
    ReconciliationSetting,
    MatchStatus,
    ConfidenceTier
)
from app.services.audit_service import log_audit

logger = logging.getLogger("finrecon.engine")

def to_cents(val: Optional[Any]) -> int:
    """Convert monetary float/decimal to integer minor currency units (cents) to eliminate float error."""
    if val is None:
        return 0
    d = Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)

def from_cents(cents: int) -> float:
    """Convert integer minor currency units back to standard float with 2 decimal precision."""
    return float(Decimal(cents) / Decimal(100))

def normalize_text(text: Optional[str]) -> str:
    """Normalize text for consistent string matching."""
    if not text:
        return ""
    return "".join(c.lower() for c in text if c.isalnum() or c.isspace()).strip()

def get_reconciliation_settings(db: Session) -> ReconciliationSetting:
    """Retrieve current reconciliation settings or create defaults."""
    setting = db.query(ReconciliationSetting).first()
    if not setting:
        setting = ReconciliationSetting()
        db.add(setting)
        db.commit()
    return setting

def evaluate_pair(
    invoice: Invoice,
    payment: Payment,
    settings: ReconciliationSetting
) -> Dict[str, Any]:
    """
    Evaluate similarity between a specific invoice and payment receipt.
    Calculates weighted confidence score (0-100) and produces full explanation.
    """
    notes: List[str] = []
    
    # Check if payment is valid for reconciliation
    if payment.transaction_type == TransactionType.DEBIT.value:
        return {
            "score": 0.0,
            "tier": ConfidenceTier.LOW.value,
            "strategy": "Excluded Debit Transaction",
            "explanation": "Debits and non-receipt transactions are excluded from reconciliation.",
            "details": {},
            "eligible": False
        }

    # Strict Currency Incompatibility Check
    inv_curr = (invoice.currency or "USD").strip().upper()
    pay_curr = (payment.currency or "USD").strip().upper()
    if inv_curr != pay_curr:
        return {
            "score": 0.0,
            "tier": ConfidenceTier.LOW.value,
            "strategy": "Currency Mismatch",
            "explanation": f"Currency incompatibility: Invoice ({inv_curr}) and Payment ({pay_curr}) differ. Cross-currency matching requires authorized exchange conversion.",
            "details": {"invoice_currency": inv_curr, "payment_currency": pay_curr, "is_currency_mismatch": True},
            "eligible": False
        }

    # Weight components
    w_inv = float(settings.weight_invoice_number)
    w_cust = float(settings.weight_customer_name)
    w_amt = float(settings.weight_amount)
    w_date = float(settings.weight_date_proximity)
    total_weights = w_inv + w_cust + w_amt + w_date
    if total_weights <= 0:
        total_weights = 100.0

    # 1. Invoice Number Match in reference or description (Weight: w_inv)
    inv_num_clean = normalize_text(invoice.invoice_number)
    payment_ref_clean = normalize_text(payment.transaction_reference)
    payment_desc_clean = normalize_text(payment.bank_description)

    inv_score_fraction = 0.0
    if inv_num_clean:
        if inv_num_clean == payment_ref_clean:
            inv_score_fraction = 1.0
            notes.append(f"Exact match on transaction reference '{payment.transaction_reference}' and invoice number '{invoice.invoice_number}'.")
        elif inv_num_clean in payment_desc_clean or inv_num_clean in payment_ref_clean:
            inv_score_fraction = 1.0
            notes.append(f"Invoice number '{invoice.invoice_number}' explicitly identified in payment description/reference.")
        else:
            # Check partial token match (e.g. without prefix 'INV-')
            core_num = inv_num_clean.replace("inv", "").replace("invoice", "").strip()
            if len(core_num) >= 3 and (core_num in payment_desc_clean or core_num in payment_ref_clean):
                inv_score_fraction = 0.85
                notes.append(f"Core invoice identifier '{core_num}' found in bank narrative.")
            else:
                fuzzy_num_score = fuzz.partial_ratio(inv_num_clean, payment_desc_clean)
                if fuzzy_num_score >= 85:
                    inv_score_fraction = (fuzzy_num_score / 100.0) * 0.75
                    notes.append(f"Fuzzy invoice number match ({fuzzy_num_score:.1f}% similarity).")

    score_invoice = inv_score_fraction * w_inv

    # 2. Customer Name Match (Weight: w_cust)
    cust_score_fraction = 0.0
    sim_ratio = 0.0
    if invoice.customer_name and payment.customer_name:
        cust_inv = normalize_text(invoice.customer_name)
        cust_pay = normalize_text(payment.customer_name)
        
        if cust_inv == cust_pay:
            cust_score_fraction = 1.0
            sim_ratio = 100.0
            notes.append(f"Exact customer name match: '{invoice.customer_name}'.")
        else:
            ratio1 = fuzz.token_sort_ratio(cust_inv, cust_pay)
            ratio2 = fuzz.partial_ratio(cust_inv, cust_pay)
            sim_ratio = max(ratio1, ratio2)
            if sim_ratio >= 90:
                cust_score_fraction = 1.0
                notes.append(f"High-confidence customer name match: {sim_ratio:.1f}% ('{invoice.customer_name}' vs '{payment.customer_name}').")
            elif sim_ratio >= 70:
                cust_score_fraction = sim_ratio / 100.0
                notes.append(f"Fuzzy customer name match: {sim_ratio:.1f}% ('{invoice.customer_name}' vs '{payment.customer_name}').")
    elif payment.bank_description and invoice.customer_name:
        # Customer name might be embedded in the bank narrative
        cust_inv = normalize_text(invoice.customer_name)
        desc_norm = normalize_text(payment.bank_description)
        if cust_inv in desc_norm:
            cust_score_fraction = 0.90
            sim_ratio = 90.0
            notes.append(f"Customer name '{invoice.customer_name}' detected inside payment description.")
        else:
            sim_ratio = fuzz.partial_ratio(cust_inv, desc_norm)
            if sim_ratio >= 80:
                cust_score_fraction = (sim_ratio / 100.0) * 0.8
                notes.append(f"Fuzzy customer name match in narrative: {sim_ratio:.1f}%.")

    score_customer = cust_score_fraction * w_cust

    # 3. Amount Match (Weight: w_amt) - Authoritative integer-cent precision
    amount_score_fraction = 0.0
    inv_rem_cents = to_cents(invoice.remaining_amount)
    pay_unalloc_cents = to_cents(payment.unallocated_amount)
    inv_total_cents = to_cents(invoice.total_amount)
    pay_total_cents = to_cents(payment.amount)

    inv_rem = from_cents(inv_rem_cents)
    pay_unalloc = from_cents(pay_unalloc_cents)
    inv_total = from_cents(inv_total_cents)
    pay_total = from_cents(pay_total_cents)

    # Check exact remaining match
    if inv_rem_cents == pay_unalloc_cents and inv_rem_cents > 0:
        amount_score_fraction = 1.0
        notes.append(f"Exact amount match: payment unallocated ${pay_unalloc:.2f} equals invoice remaining ${inv_rem:.2f}.")
    # Check exact total match
    elif inv_total_cents == pay_total_cents and inv_total_cents > 0:
        amount_score_fraction = 0.95
        notes.append(f"Exact total match: payment ${pay_total:.2f} equals original invoice total ${inv_total:.2f}.")
    # Check partial payment (payment is less than remaining balance)
    elif 0 < pay_unalloc_cents < inv_rem_cents:
        amount_score_fraction = 0.70
        notes.append(f"Partial payment candidate: payment ${pay_unalloc:.2f} will partially settle ${inv_rem:.2f} remaining.")
    # Check overpayment (payment unallocated exceeds invoice remaining balance)
    elif pay_unalloc_cents > inv_rem_cents and inv_rem_cents > 0:
        amount_score_fraction = 0.40
        notes.append(f"Payment unallocated (${pay_unalloc:.2f}) exceeds invoice balance (${inv_rem:.2f}). Needs split or overpayment review.")
    else:
        amount_score_fraction = 0.0

    score_amount = amount_score_fraction * w_amt

    # 4. Date Proximity (Weight: w_date)
    date_score_fraction = 0.0
    # Proximity to either invoice date or due date
    diff_inv = abs((payment.payment_date - invoice.invoice_date).days)
    diff_due = abs((payment.payment_date - invoice.due_date).days)
    days_diff = min(diff_inv, diff_due)
    tolerance = settings.date_tolerance_days

    if days_diff <= 7:
        date_score_fraction = 1.0
        notes.append(f"Payment date {payment.payment_date} is within {days_diff} days of invoice date/due date.")
    elif days_diff <= tolerance:
        date_score_fraction = 1.0 - (days_diff / float(tolerance)) * 0.5
        notes.append(f"Payment date within {days_diff} days (tolerance: {tolerance} days).")
    else:
        date_score_fraction = 0.0
        notes.append(f"Payment date {payment.payment_date} is {days_diff} days away from invoice dates (exceeds {tolerance} days).")

    score_date = date_score_fraction * w_date

    # Total Score Normalized to 0-100
    total_raw_score = score_invoice + score_customer + score_amount + score_date
    final_score = round(min(100.0, max(0.0, (total_raw_score / total_weights) * 100.0)), 1)

    # Strategy classification
    strategy = "Rule-Based Reconciliation"
    if inv_score_fraction >= 0.85 and amount_score_fraction >= 0.95:
        strategy = "Exact Invoice # and Exact Amount"
    elif inv_score_fraction >= 0.85:
        strategy = "Invoice Reference Match"
    elif cust_score_fraction >= 0.9 and amount_score_fraction >= 0.95:
        strategy = "Customer & Exact Amount Match"
    elif cust_score_fraction >= 0.7:
        strategy = "Fuzzy Customer & Date Proximity"
    elif pay_unalloc < inv_rem:
        strategy = "Partial Payment Allocation"

    # Tier classification
    is_suspicious = False
    if payment.is_suspicious or payment.is_duplicate:
        tier = ConfidenceTier.SUSPICIOUS.value
        is_suspicious = True
        notes.append(f"Suspicious flag: {payment.suspicion_reason or 'Payment flagged for manual review'}")
    elif pay_unalloc > inv_rem and inv_score_fraction >= 0.85:
        # Potential overpayment
        tier = ConfidenceTier.SUSPICIOUS.value
        is_suspicious = True
        notes.append("Overpayment warning: Payment exceeds invoice remaining balance. Suspicious, needs review.")
    elif final_score >= settings.auto_match_threshold:
        tier = ConfidenceTier.HIGH.value
    elif final_score >= settings.review_queue_threshold:
        tier = ConfidenceTier.MEDIUM.value
    else:
        tier = ConfidenceTier.LOW.value

    # Build comprehensive human explanation
    explanation_lines = [
        f"Invoice {invoice.invoice_number} (Customer: '{invoice.customer_name}', Remaining: ${inv_rem:.2f}) evaluated against Payment {payment.transaction_reference} (Payer: '{payment.customer_name or 'N/A'}', Unallocated: ${pay_unalloc:.2f}).",
        f"Overall Confidence Score: {final_score}/100 [{tier}]. Strategy: {strategy}.",
        "Criteria Breakdown: " + "; ".join(notes)
    ]
    explanation = "\n".join(explanation_lines)

    details = {
        "invoice_number_score": round(score_invoice, 1),
        "customer_name_score": round(score_customer, 1),
        "amount_score": round(score_amount, 1),
        "date_score": round(score_date, 1),
        "raw_score": final_score,
        "customer_similarity_ratio": round(sim_ratio, 1),
        "days_difference": days_diff,
        "is_suspicious": is_suspicious,
        "notes": notes
    }

    return {
        "score": final_score,
        "tier": tier,
        "strategy": strategy,
        "explanation": explanation,
        "details": details,
        "eligible": True
    }

def run_reconciliation_pipeline(
    db: Session,
    auto_approve_high: bool = True,
    re_evaluate_all: bool = False,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Execute end-to-end intelligent multi-pass reconciliation:
    Pass 1: Direct 1-to-1 matches (Exact reference & high fuzzy)
    Pass 2: Partial payments & multiple payments per invoice
    Pass 3: Split payment across multiple invoices
    """
    settings = get_reconciliation_settings(db)
    auto_match_policy = settings.auto_match_enabled and auto_approve_high

    # If re-evaluating, clear non-approved proposed matches
    if re_evaluate_all:
        db.query(ReconciliationMatch).filter(
            ReconciliationMatch.status == MatchStatus.PROPOSED.value
        ).delete(synchronize_session=False)
        db.commit()

    # Open invoices with remaining balance > 0.01
    open_invoices = db.query(Invoice).filter(
        Invoice.remaining_amount > 0.01,
        Invoice.status != InvoiceStatus.PAID.value
    ).order_by(Invoice.due_date.asc()).all()

    # Unallocated incoming credit payments
    available_payments = db.query(Payment).filter(
        Payment.transaction_type == TransactionType.CREDIT.value,
        Payment.unallocated_amount > 0.01,
        Payment.status != PaymentStatus.EXCLUDED.value
    ).order_by(Payment.payment_date.asc()).all()

    # Set of existing proposed or approved match pairs to avoid duplicate proposals
    existing_pairs = set(
        (m.invoice_id, m.payment_id) for m in db.query(
            ReconciliationMatch.invoice_id, ReconciliationMatch.payment_id
        ).filter(
            ReconciliationMatch.status.in_([MatchStatus.PROPOSED.value, MatchStatus.APPROVED.value, MatchStatus.MANUAL_ALLOCATED.value])
        ).all()
    )

    matches_generated = 0
    auto_approved_count = 0
    review_queue_count = 0
    unmatched_count = 0
    suspicious_count = 0

    proposed_matches: List[ReconciliationMatch] = []

    # -------------------------------------------------------------
    # PASS 1: Direct Matching (Exact Invoice Reference / Exact Amount)
    # -------------------------------------------------------------
    ambiguity_margin = float(getattr(settings, "ambiguity_margin", 5.0) or 5.0)

    for invoice in open_invoices:
        if invoice.remaining_amount <= 0.01:
            continue

        candidates: List[Tuple[Dict[str, Any], Payment]] = []

        for payment in available_payments:
            if payment.unallocated_amount <= 0.01:
                continue
            if (invoice.id, payment.id) in existing_pairs:
                continue

            eval_res = evaluate_pair(invoice, payment, settings)
            if not eval_res["eligible"]:
                continue

            if eval_res["score"] >= settings.review_queue_threshold:
                candidates.append((eval_res, payment))

        if not candidates:
            continue

        # Sort candidates descending by confidence score
        candidates.sort(key=lambda x: x[0]["score"], reverse=True)
        best_eval, best_payment = candidates[0]

        # Ambiguity margin check
        is_ambiguous = False
        if len(candidates) > 1:
            second_eval, second_payment = candidates[1]
            score_gap = round(best_eval["score"] - second_eval["score"], 1)
            if score_gap < ambiguity_margin:
                is_ambiguous = True
                best_eval["tier"] = ConfidenceTier.MEDIUM.value
                best_eval["details"]["is_ambiguous"] = True
                best_eval["details"]["competing_payment"] = second_payment.transaction_reference
                best_eval["details"]["score_gap"] = score_gap
                ambiguity_note = (
                    f"Ambiguity Warning: Competing payment '{second_payment.transaction_reference}' scored {second_eval['score']:.1f}% "
                    f"(margin gap: {score_gap:.1f}% < {ambiguity_margin:.1f}%). Requires human review in Review Queue."
                )
                best_eval["details"]["notes"].append(ambiguity_note)
                best_eval["explanation"] += f"\n[!] {ambiguity_note}"

        inv_rem_c = to_cents(invoice.remaining_amount)
        pay_unalloc_c = to_cents(best_payment.unallocated_amount)
        alloc_amt_c = min(inv_rem_c, pay_unalloc_c)
        alloc_amt = from_cents(alloc_amt_c)

        # Check for overpayment condition
        if pay_unalloc_c > inv_rem_c and best_eval["details"].get("invoice_number_score", 0) > 0:
            best_eval["tier"] = ConfidenceTier.SUSPICIOUS.value
            best_eval["strategy"] = "Overpayment / Split Candidate"

        match_record = ReconciliationMatch(
            invoice_id=invoice.id,
            payment_id=best_payment.id,
            allocated_amount=alloc_amt,
            confidence_score=best_eval["score"],
            confidence_tier=best_eval["tier"],
            status=MatchStatus.PROPOSED.value,
            strategy_applied=best_eval["strategy"],
            explanation=best_eval["explanation"],
            match_details=json.dumps(best_eval["details"], default=str)
        )

        # Auto-approval check: Never auto-approve if ambiguous or suspicious
        if (
            auto_match_policy and
            not is_ambiguous and
            best_eval["tier"] == ConfidenceTier.HIGH.value and
            not best_eval["details"].get("is_suspicious") and
            not best_payment.is_suspicious and
            alloc_amt > 0
        ):
            try:
                invoice.paid_amount = from_cents(to_cents(invoice.paid_amount) + alloc_amt_c)
                invoice.remaining_amount = from_cents(max(0, inv_rem_c - alloc_amt_c))
                invoice.update_status()

                best_payment.allocated_amount = from_cents(to_cents(best_payment.allocated_amount) + alloc_amt_c)
                best_payment.unallocated_amount = from_cents(max(0, pay_unalloc_c - alloc_amt_c))
                best_payment.update_status()

                match_record.status = MatchStatus.APPROVED.value
                match_record.approved_by_user_id = user_id
                match_record.approved_at = datetime.now(timezone.utc)
                auto_approved_count += 1
            except Exception as ex:
                logger.error(f"Failed auto-approval for invoice {invoice.id} and payment {best_payment.id}: {ex}")
                db.rollback()
                match_record.status = MatchStatus.PROPOSED.value

        db.add(match_record)
        existing_pairs.add((invoice.id, best_payment.id))
        matches_generated += 1

        if match_record.status == MatchStatus.PROPOSED.value:
            if best_eval["tier"] == ConfidenceTier.SUSPICIOUS.value:
                suspicious_count += 1
            else:
                review_queue_count += 1

    db.commit()

    # -------------------------------------------------------------
    # PASS 2: Split Payments & Multi-Invoice Settlements
    # (Payments with remaining unallocated balance from same customer)
    # -------------------------------------------------------------
    for payment in available_payments:
        if payment.unallocated_amount <= 0.01 or payment.is_suspicious or not payment.customer_name:
            continue

        # Find any other open invoices for this same customer
        norm_cust = normalize_text(payment.customer_name)
        customer_invoices = [
            inv for inv in open_invoices
            if inv.remaining_amount > 0.01 and
            normalize_text(inv.customer_name) == norm_cust and
            (inv.id, payment.id) not in existing_pairs
        ]

        for inv in customer_invoices:
            if payment.unallocated_amount <= 0.01:
                break
            
            alloc_amt = round(min(inv.remaining_amount, payment.unallocated_amount), 2)
            if alloc_amt <= 0:
                continue

            eval_res = evaluate_pair(inv, payment, settings)
            split_strategy = "Split Payment Across Invoices"
            explanation = (
                f"Split payment allocation: Remainder of payment {payment.transaction_reference} "
                f"allocated ${alloc_amt:.2f} to open invoice {inv.invoice_number} for customer '{inv.customer_name}'."
            )

            match_record = ReconciliationMatch(
                invoice_id=inv.id,
                payment_id=payment.id,
                allocated_amount=alloc_amt,
                confidence_score=max(70.0, eval_res["score"]),
                confidence_tier=ConfidenceTier.MEDIUM.value,  # Split payments sent to review queue for human confirmation
                status=MatchStatus.PROPOSED.value,
                strategy_applied=split_strategy,
                explanation=explanation,
                match_details=json.dumps(eval_res["details"], default=str)
            )

            db.add(match_record)
            existing_pairs.add((inv.id, payment.id))
            matches_generated += 1
            review_queue_count += 1

    db.commit()

    # Trigger anomaly detection to update discrepancy and risk alert records
    try:
        from app.services.anomaly_service import detect_anomalies
        anomalies = detect_anomalies(db, user_id=user_id)
        logger.info(f"Anomaly scan completed: {len(anomalies)} active alerts.")
    except Exception as anom_err:
        logger.warning(f"Anomaly detection notice: {anom_err}")

    # Log reconciliation execution audit
    log_audit(
        db,
        action="RECONCILIATION_RUN",
        entity_type="SYSTEM",
        entity_id=None,
        description=f"Reconciliation engine completed. Generated {matches_generated} matches ({auto_approved_count} auto-approved, {review_queue_count} in review queue, {suspicious_count} suspicious flags).",
        details={
            "matches_generated": matches_generated,
            "auto_approved": auto_approved_count,
            "review_queue": review_queue_count,
            "suspicious": suspicious_count,
            "auto_match_enabled": auto_match_policy
        },
        user_id=user_id
    )
    db.commit()

    return {
        "matches_generated": matches_generated,
        "auto_approved_count": auto_approved_count,
        "review_queue_count": review_queue_count,
        "suspicious_count": suspicious_count
    }

def approve_match(db: Session, match_id: int, user_id: Optional[int] = None) -> ReconciliationMatch:
    """
    Approve proposed reconciliation match.
    Enforces atomic transaction: updates invoice remaining/paid balance, payment allocated/unallocated,
    verifies no over-allocation without flag, logs audit trail, and rolls back on any error.
    """
    match = db.query(ReconciliationMatch).filter(ReconciliationMatch.id == match_id).first()
    if not match:
        raise ValueError(f"Match with id {match_id} not found.")

    if match.status == MatchStatus.APPROVED.value:
        return match

    invoice = db.query(Invoice).filter(Invoice.id == match.invoice_id).with_for_update().first()
    payment = db.query(Payment).filter(Payment.id == match.payment_id).with_for_update().first()

    if not invoice or not payment:
        raise ValueError("Associated invoice or payment records missing.")

    alloc_c = to_cents(match.allocated_amount)
    if alloc_c <= 0:
        raise ValueError("Allocated amount must be positive.")

    pay_unalloc_c = to_cents(payment.unallocated_amount)
    inv_rem_c = to_cents(invoice.remaining_amount)
    alloc_amt = from_cents(alloc_c)

    # Integrity rules check with integer cents precision
    if alloc_c > pay_unalloc_c:
        raise ValueError(f"Cannot allocate ${alloc_amt:.2f}: exceeds payment unallocated balance ${from_cents(pay_unalloc_c):.2f}.")

    if alloc_c > inv_rem_c:
        # Overpayment safeguard
        match.confidence_tier = ConfidenceTier.SUSPICIOUS.value
        raise ValueError(f"Overpayment alert: Cannot allocate ${alloc_amt:.2f} beyond invoice remaining balance of ${from_cents(inv_rem_c):.2f}.")

    try:
        # Update Invoice
        invoice.paid_amount = from_cents(to_cents(invoice.paid_amount) + alloc_c)
        invoice.remaining_amount = from_cents(max(0, inv_rem_c - alloc_c))
        invoice.update_status()

        # Update Payment
        payment.allocated_amount = from_cents(to_cents(payment.allocated_amount) + alloc_c)
        payment.unallocated_amount = from_cents(max(0, pay_unalloc_c - alloc_c))
        payment.update_status()

        # Update Match status
        match.status = MatchStatus.APPROVED.value
        match.approved_by_user_id = user_id
        match.approved_at = datetime.now(timezone.utc)

        # Audit log
        log_audit(
            db,
            action="RECONCILE_APPROVE",
            entity_type="MATCH",
            entity_id=match.id,
            description=f"Approved match #{match.id}: Allocated ${alloc_amt:.2f} from Payment '{payment.transaction_reference}' to Invoice '{invoice.invoice_number}'.",
            details={
                "match_id": match.id,
                "invoice_number": invoice.invoice_number,
                "payment_reference": payment.transaction_reference,
                "allocated_amount": alloc_amt,
                "invoice_remaining": invoice.remaining_amount,
                "payment_unallocated": payment.unallocated_amount
            },
            user_id=user_id
        )

        db.commit()
        return match
    except Exception as e:
        db.rollback()
        logger.error(f"Error during match approval: {e}")
        raise

def reject_match(db: Session, match_id: int, reason: Optional[str] = None, user_id: Optional[int] = None) -> ReconciliationMatch:
    """Reject a proposed match with optional audit explanation."""
    match = db.query(ReconciliationMatch).filter(ReconciliationMatch.id == match_id).first()
    if not match:
        raise ValueError(f"Match with id {match_id} not found.")

    if match.status == MatchStatus.APPROVED.value:
        raise ValueError("Cannot reject an already approved match without unmatching it first.")

    match.status = MatchStatus.REJECTED.value
    match.rejected_by_user_id = user_id
    match.rejected_at = datetime.now(timezone.utc)
    match.rejection_reason = reason or "Rejected during reviewer evaluation."

    log_audit(
        db,
        action="RECONCILE_REJECT",
        entity_type="MATCH",
        entity_id=match.id,
        description=f"Rejected match #{match.id} (Invoice #{match.invoice_id}, Payment #{match.payment_id}). Reason: {match.rejection_reason}",
        details={"match_id": match.id, "reason": match.rejection_reason},
        user_id=user_id
    )
    db.commit()
    return match

def manual_allocate(
    db: Session,
    invoice_id: int,
    payment_id: int,
    amount: float,
    user_id: Optional[int] = None,
    notes: Optional[str] = None
) -> ReconciliationMatch:
    """
    Manually match and allocate a specified dollar amount between any invoice and payment.
    Executed in an atomic transaction with full rollback and validation.
    """
    amount = round(amount, 2)
    if amount <= 0:
        raise ValueError("Allocation amount must be greater than zero.")

    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().first()
    payment = db.query(Payment).filter(Payment.id == payment_id).with_for_update().first()

    if not invoice:
        raise ValueError(f"Invoice #{invoice_id} not found.")
    if not payment:
        raise ValueError(f"Payment #{payment_id} not found.")

    if payment.transaction_type == TransactionType.DEBIT.value:
        raise ValueError("Cannot reconcile against a debit/withdrawal transaction.")

    # Integrity rules
    if amount > round(payment.unallocated_amount, 2) + 0.01:
        raise ValueError(f"Requested allocation ${amount:.2f} exceeds payment unallocated balance (${payment.unallocated_amount:.2f}).")

    if amount > round(invoice.remaining_amount, 2) + 0.01:
        raise ValueError(f"Requested allocation ${amount:.2f} exceeds invoice remaining balance (${invoice.remaining_amount:.2f}). Flagged as overpayment; cannot over-allocate.")

    try:
        alloc_c = to_cents(amount)
        invoice.paid_amount = from_cents(to_cents(invoice.paid_amount) + alloc_c)
        invoice.remaining_amount = from_cents(max(0, to_cents(invoice.remaining_amount) - alloc_c))
        invoice.update_status()

        # Update Payment
        payment.allocated_amount = from_cents(to_cents(payment.allocated_amount) + alloc_c)
        payment.unallocated_amount = from_cents(max(0, to_cents(payment.unallocated_amount) - alloc_c))
        payment.update_status()

        # Create Reconciliation Match Record
        explanation = (
            f"Manual allocation performed by analyst. Allocated ${amount:.2f} from Payment "
            f"'{payment.transaction_reference}' to Invoice '{invoice.invoice_number}'. "
            f"Notes: {notes or 'N/A'}"
        )

        match = ReconciliationMatch(
            invoice_id=invoice.id,
            payment_id=payment.id,
            allocated_amount=amount,
            confidence_score=100.0,
            confidence_tier=ConfidenceTier.HIGH.value,
            status=MatchStatus.MANUAL_ALLOCATED.value,
            strategy_applied="Manual Analyst Allocation",
            explanation=explanation,
            match_details=json.dumps({"notes": notes, "manual": True}),
            approved_by_user_id=user_id,
            approved_at=datetime.now(timezone.utc)
        )
        db.add(match)

        log_audit(
            db,
            action="MANUAL_ALLOCATE",
            entity_type="MATCH",
            entity_id=None,
            description=f"Manual allocation: ${amount:.2f} from Payment '{payment.transaction_reference}' to Invoice '{invoice.invoice_number}'.",
            details={
                "invoice_id": invoice.id,
                "payment_id": payment.id,
                "amount": amount,
                "notes": notes
            },
            user_id=user_id
        )

        db.commit()
        db.refresh(match)
        return match
    except Exception as e:
        db.rollback()
        logger.error(f"Manual allocation error: {e}")
        raise

def unmatch_allocation(db: Session, match_id: int, user_id: Optional[int] = None) -> bool:
    """
    Unmatch / rollback an approved match and restore balances to invoice and payment safely.
    """
    match = db.query(ReconciliationMatch).filter(ReconciliationMatch.id == match_id).first()
    if not match:
        raise ValueError(f"Match #{match_id} not found.")

    if match.status not in [MatchStatus.APPROVED.value, MatchStatus.MANUAL_ALLOCATED.value]:
        # Just delete proposed match
        db.delete(match)
        db.commit()
        return True

    invoice = db.query(Invoice).filter(Invoice.id == match.invoice_id).with_for_update().first()
    payment = db.query(Payment).filter(Payment.id == match.payment_id).with_for_update().first()

    try:
        alloc_c = to_cents(match.allocated_amount)
        alloc = from_cents(alloc_c)
        if invoice:
            inv_paid_c = to_cents(invoice.paid_amount)
            inv_rem_c = to_cents(invoice.remaining_amount)
            inv_tot_c = to_cents(invoice.total_amount)
            invoice.paid_amount = from_cents(max(0, inv_paid_c - alloc_c))
            invoice.remaining_amount = from_cents(min(inv_tot_c, inv_rem_c + alloc_c))
            invoice.update_status()

        if payment:
            pay_alloc_c = to_cents(payment.allocated_amount)
            pay_unalloc_c = to_cents(payment.unallocated_amount)
            pay_tot_c = to_cents(payment.amount)
            payment.allocated_amount = from_cents(max(0, pay_alloc_c - alloc_c))
            payment.unallocated_amount = from_cents(min(pay_tot_c, pay_unalloc_c + alloc_c))
            payment.update_status()

        log_audit(
            db,
            action="RECONCILE_UNMATCH",
            entity_type="MATCH",
            entity_id=match.id,
            description=f"Unmatched allocation #{match.id}: Reverted ${alloc:.2f} back to Invoice #{match.invoice_id} and Payment #{match.payment_id}.",
            details={"match_id": match.id, "reverted_amount": alloc},
            user_id=user_id
        )

        db.delete(match)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Unmatch allocation error: {e}")
        raise
