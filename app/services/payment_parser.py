import io
import re
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
from sqlalchemy.orm import Session
from dateutil import parser as date_parser

from app.models.payment import Payment, PaymentStatus, TransactionType
from app.services.audit_service import log_audit

logger = logging.getLogger("finrecon.payment_parser")

PAYMENT_COLUMN_MAPPINGS = {
    "transaction_reference": ["transaction_reference", "reference", "ref", "txn_id", "transaction_id", "trans_ref", "cheque_no", "check_number", "id"],
    "customer_name": ["customer_name", "customer", "payer", "sender", "originator", "client", "counterparty", "remitter"],
    "payment_date": ["payment_date", "date", "posting_date", "value_date", "trans_date", "booking_date", "txn_date"],
    "amount": ["amount", "credit", "deposit", "amount_received", "trans_amount", "gross_amount"],
    "currency": ["currency", "curr"],
    "payment_method": ["payment_method", "method", "channel", "payment_type"],
    "bank_description": ["bank_description", "description", "narrative", "particulars", "memo", "remarks", "details"],
    "transaction_type": ["transaction_type", "entry_type", "cr_dr", "type"]
}

DEBIT_KEYWORDS = ["fee", "withdrawal", "service charge", "atm", "interest charge", "debit", "dr", "payout", "transfer out", "card purchase"]

def clean_col(col: str) -> str:
    c = str(col).strip().lower()
    return re.sub(r'[\s\-_#]+', '_', c)

def find_matched_col(df_cols: List[str], target_field: str) -> Optional[str]:
    aliases = PAYMENT_COLUMN_MAPPINGS.get(target_field, [])
    for col in df_cols:
        norm = clean_col(col)
        if norm in aliases or norm == target_field:
            return col
    return None

def parse_date_safe(val: Any) -> date:
    if val is None or pd.isna(val):
        return date.today()
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return date_parser.parse(str(val)).date()
    except Exception:
        return date.today()

def parse_float_safe(val: Any, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    is_negative = '-' in s or ('(' in s and ')' in s)
    cleaned = re.sub(r'[^\d.]', '', s)
    try:
        res = float(cleaned)
        return -res if is_negative else res
    except Exception:
        return default

def parse_bank_statement(
    file_bytes: bytes,
    filename: str,
    db: Session,
    user_id: Optional[int] = None
) -> Tuple[int, int, int, int, int, List[str]]:
    """
    Parse bank statements (CSV or Excel).
    Returns:
    (total_processed, receipts_imported, debits_excluded, duplicates_detected, suspicious_count, errors)
    """
    errors: List[str] = []
    total_processed = 0
    receipts_imported = 0
    debits_excluded = 0
    duplicates_detected = 0
    suspicious_count = 0

    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as e:
        return 0, 0, 0, 0, 0, [f"Failed to read file: {str(e)}"]

    if df.empty:
        return 0, 0, 0, 0, 0, ["Uploaded file contains no data."]

    cols = list(df.columns)
    ref_col = find_matched_col(cols, "transaction_reference")
    amt_col = find_matched_col(cols, "amount")

    if not amt_col:
        return 0, 0, 0, 0, 0, ["Required column 'Amount' or 'Credit' could not be found."]

    date_col = find_matched_col(cols, "payment_date")
    customer_col = find_matched_col(cols, "customer_name")
    desc_col = find_matched_col(cols, "bank_description")
    method_col = find_matched_col(cols, "payment_method")
    curr_col = find_matched_col(cols, "currency")
    type_col = find_matched_col(cols, "transaction_type")

    # Fetch existing payment references
    existing_refs = set(x[0] for x in db.query(Payment.transaction_reference).all())
    
    # Pre-fetch existing recent payments for duplicate candidate checking
    existing_payments = db.query(Payment).all()

    new_payments = []

    for idx, row in df.iterrows():
        try:
            total_processed += 1
            raw_amt = parse_float_safe(row[amt_col])
            raw_ref = str(row[ref_col]).strip() if ref_col and pd.notna(row[ref_col]) else None
            
            if not raw_ref or raw_ref.lower() == "nan":
                raw_ref = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{idx+1}"

            desc = str(row[desc_col]).strip() if desc_col and pd.notna(row[desc_col]) else ""
            customer = str(row[customer_col]).strip() if customer_col and pd.notna(row[customer_col]) else None
            if customer and customer.lower() == "nan":
                customer = None

            payment_date = parse_date_safe(row[date_col]) if date_col else date.today()
            method = str(row[method_col]).strip() if method_col and pd.notna(row[method_col]) else "Bank Transfer"
            currency = str(row[curr_col]).strip().upper() if curr_col and pd.notna(row[curr_col]) else "USD"

            # Check transaction type: CREDIT vs DEBIT
            is_debit = False
            if type_col and pd.notna(row[type_col]):
                val_type = str(row[type_col]).strip().upper()
                if "DEBIT" in val_type or "DR" in val_type or "WITHDRAWAL" in val_type:
                    is_debit = True

            if raw_amt < 0:
                is_debit = True
                raw_amt = abs(raw_amt)

            # Check keywords in description
            desc_lower = desc.lower()
            if any(kw in desc_lower for kw in DEBIT_KEYWORDS) and not is_debit:
                # If explicitly marked as credit in type column, don't override
                if not (type_col and "CR" in str(row[type_col]).upper()):
                    is_debit = True

            # If it's a debit (withdrawal/charge), store as EXCLUDED and do not reconcile
            if is_debit:
                debits_excluded += 1
                status = PaymentStatus.EXCLUDED.value
                tx_type = TransactionType.DEBIT.value
            else:
                receipts_imported += 1
                status = PaymentStatus.UNMATCHED.value
                tx_type = TransactionType.CREDIT.value

            # Check duplicate reference
            is_duplicate = False
            is_suspicious = False
            suspicion_reason = None

            if raw_ref in existing_refs:
                is_duplicate = True
                is_suspicious = True
                suspicion_reason = f"Duplicate reference '{raw_ref}' already recorded in ledger"
                duplicates_detected += 1
                suspicious_count += 1
                status = PaymentStatus.SUSPICIOUS.value
            else:
                existing_refs.add(raw_ref)

                # Check duplicate candidate heuristic: same amount, same customer, within 2 days
                if not is_debit and customer:
                    for ep in existing_payments:
                        if (
                            ep.customer_name and
                            ep.customer_name.lower() == customer.lower() and
                            abs(ep.amount - raw_amt) < 0.01 and
                            abs((ep.payment_date - payment_date).days) <= 2
                        ):
                            is_suspicious = True
                            suspicion_reason = f"Potential duplicate payment candidate: identical amount ${raw_amt:.2f} for '{customer}' within 2 days of {ep.transaction_reference}."
                            suspicious_count += 1
                            status = PaymentStatus.SUSPICIOUS.value
                            break

            payment = Payment(
                transaction_reference=raw_ref,
                customer_name=customer,
                payment_date=payment_date,
                amount=round(raw_amt, 2),
                allocated_amount=0.0,
                unallocated_amount=round(raw_amt, 2) if not is_debit else 0.0,
                currency=currency,
                payment_method=method,
                bank_description=desc if desc else f"Bank statement transaction {raw_ref}",
                transaction_type=tx_type,
                import_source="CSV" if filename.lower().endswith(".csv") else "Excel",
                import_filename=filename,
                is_duplicate=is_duplicate,
                is_suspicious=is_suspicious,
                suspicion_reason=suspicion_reason,
                status=status
            )
            new_payments.append(payment)
        except Exception as row_err:
            errors.append(f"Row {idx+2}: {str(row_err)}")

    if new_payments:
        db.add_all(new_payments)
        db.commit()
        log_audit(
            db,
            action="PAYMENT_IMPORT",
            entity_type="PAYMENT",
            entity_id=None,
            description=f"Imported bank statement {filename}. Total: {total_processed}, Receipts: {receipts_imported}, Debits excluded: {debits_excluded}, Suspicious: {suspicious_count}",
            details={
                "total": total_processed,
                "receipts": receipts_imported,
                "debits_excluded": debits_excluded,
                "duplicates": duplicates_detected,
                "suspicious": suspicious_count,
                "errors": errors
            },
            user_id=user_id
        )
        db.commit()

    return total_processed, receipts_imported, debits_excluded, duplicates_detected, suspicious_count, errors
