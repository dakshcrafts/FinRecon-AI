import io
import re
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
from sqlalchemy.orm import Session
from dateutil import parser as date_parser

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit_service import log_audit

logger = logging.getLogger("finrecon.invoice_parser")

COLUMN_MAPPINGS = {
    "invoice_number": ["invoice_number", "invoice_no", "inv_no", "invoiceno", "invoice #", "bill_no", "bill_number", "id", "reference"],
    "customer_name": ["customer_name", "customer", "client_name", "client", "buyer", "billed_to", "company", "account_name"],
    "customer_email": ["customer_email", "email", "client_email", "contact_email"],
    "invoice_date": ["invoice_date", "inv_date", "date", "issue_date", "bill_date", "created_date"],
    "due_date": ["due_date", "payment_due", "due", "expiry_date", "deadline"],
    "total_amount": ["total_amount", "total", "amount", "inv_amount", "gross_amount", "grand_total", "balance_due"],
    "tax_amount": ["tax_amount", "tax", "vat", "gst"],
    "currency": ["currency", "curr"],
    "description": ["description", "desc", "notes", "memo", "details", "line_items"]
}

def clean_column_name(col: str) -> str:
    """Normalize column name to lowercase alphanumeric with underscores."""
    col_str = str(col).strip().lower()
    col_str = re.sub(r'[\s\-_#]+', '_', col_str)
    return col_str

def find_matched_col(df_cols: List[str], target_field: str) -> Optional[str]:
    """Find which dataframe column matches our known field aliases."""
    aliases = COLUMN_MAPPINGS.get(target_field, [])
    for col in df_cols:
        norm = clean_column_name(col)
        if norm in aliases or norm == target_field:
            return col
    return None

def parse_date_safe(val: Any) -> date:
    """Safely parse various date formats into a datetime.date."""
    if val is None or pd.isna(val):
        return date.today()
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        dt = date_parser.parse(str(val))
        return dt.date()
    except Exception:
        return date.today()

def parse_float_safe(val: Any, default: float = 0.0) -> float:
    """Safely parse currency numbers with dollar signs, commas, or spaces."""
    if val is None or pd.isna(val):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    # String cleanup
    cleaned = re.sub(r'[^\d.-]', '', str(val).strip())
    try:
        return float(cleaned)
    except Exception:
        return default

def parse_invoices_tabular(
    file_bytes: bytes,
    filename: str,
    db: Session,
    user_id: Optional[int] = None
) -> Tuple[int, int, List[str], List[str]]:
    """Parse CSV or Excel file containing invoices with duplicate prevention."""
    imported_count = 0
    skipped_count = 0
    duplicates: List[str] = []
    errors: List[str] = []

    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as e:
        return 0, 0, [], [f"Failed to read file: {str(e)}"]

    if df.empty:
        return 0, 0, [], ["Uploaded spreadsheet is empty."]

    cols = list(df.columns)
    inv_num_col = find_matched_col(cols, "invoice_number")
    customer_col = find_matched_col(cols, "customer_name")
    total_col = find_matched_col(cols, "total_amount")

    if not inv_num_col or not customer_col or not total_col:
        missing = []
        if not inv_num_col: missing.append("Invoice Number")
        if not customer_col: missing.append("Customer Name")
        if not total_col: missing.append("Total Amount")
        return 0, 0, [], [f"Missing required columns in file: {', '.join(missing)}"]

    inv_date_col = find_matched_col(cols, "invoice_date")
    due_date_col = find_matched_col(cols, "due_date")
    email_col = find_matched_col(cols, "customer_email")
    tax_col = find_matched_col(cols, "tax_amount")
    curr_col = find_matched_col(cols, "currency")
    desc_col = find_matched_col(cols, "description")

    # Fetch existing invoice numbers to check duplicates in memory efficiently
    existing_numbers = set(
        x[0] for x in db.query(Invoice.invoice_number).all()
    )

    new_invoices = []
    for idx, row in df.iterrows():
        try:
            raw_inv_num = str(row[inv_num_col]).strip()
            if not raw_inv_num or raw_inv_num.lower() == "nan":
                continue

            if raw_inv_num in existing_numbers:
                skipped_count += 1
                duplicates.append(raw_inv_num)
                continue

            customer = str(row[customer_col]).strip()
            total = parse_float_safe(row[total_col])
            if total <= 0:
                errors.append(f"Row {idx+2}: Invalid invoice total {row[total_col]}")
                continue

            inv_date = parse_date_safe(row[inv_date_col]) if inv_date_col else date.today()
            due_date = parse_date_safe(row[due_date_col]) if due_date_col else (inv_date + timedelta(days=30))
            tax = parse_float_safe(row[tax_col]) if tax_col else 0.0
            email = str(row[email_col]).strip() if email_col and pd.notna(row[email_col]) else None
            currency = str(row[curr_col]).strip().upper() if curr_col and pd.notna(row[curr_col]) else "USD"
            desc = str(row[desc_col]).strip() if desc_col and pd.notna(row[desc_col]) else f"Imported invoice {raw_inv_num}"

            status = InvoiceStatus.UNPAID.value
            if due_date < date.today():
                status = InvoiceStatus.OVERDUE.value

            invoice = Invoice(
                invoice_number=raw_inv_num,
                customer_name=customer,
                customer_email=email,
                invoice_date=inv_date,
                due_date=due_date,
                total_amount=round(total, 2),
                paid_amount=0.0,
                remaining_amount=round(total, 2),
                tax_amount=round(tax, 2),
                currency=currency,
                description=desc,
                status=status,
                import_source="CSV" if filename.lower().endswith(".csv") else "Excel",
                import_filename=filename
            )
            new_invoices.append(invoice)
            existing_numbers.add(raw_inv_num)
            imported_count += 1
        except Exception as row_err:
            errors.append(f"Row {idx+2}: {str(row_err)}")

    if new_invoices:
        db.add_all(new_invoices)
        db.commit()
        log_audit(
            db,
            action="INVOICE_IMPORT",
            entity_type="INVOICE",
            entity_id=None,
            description=f"Imported {imported_count} invoices from {filename}. Skipped {skipped_count} duplicates.",
            details={"imported": imported_count, "duplicates": duplicates, "errors": errors},
            user_id=user_id
        )
        db.commit()

    return imported_count, skipped_count, duplicates, errors

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text using pypdf or PyMuPDF with fallbacks."""
    full_text = ""
    # Try pypdf first (pure Python, highly compatible)
    if pypdf is not None:
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    full_text += t + "\n"
        except Exception as e:
            logger.debug(f"pypdf extraction notice: {e}")

    # Fallback to PyMuPDF if empty
    if not full_text.strip() and fitz is not None:
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc:
                full_text += page.get_text() + "\n"
            doc.close()
        except Exception as e:
            logger.debug(f"PyMuPDF extraction notice: {e}")

    return full_text

def parse_invoice_pdf(
    file_bytes: bytes,
    filename: str,
    db: Session,
    user_id: Optional[int] = None
) -> Tuple[int, int, List[str], List[str]]:
    """Extract and parse invoice data from a PDF document."""
    try:
        full_text = extract_text_from_pdf(file_bytes)
    except Exception as e:
        return 0, 0, [], [f"Failed to read PDF file: {str(e)}"]

    if not full_text.strip():
        return 0, 0, [], ["PDF document contains no readable text."]

    # Heuristic regex matching for key invoice fields
    inv_num_match = re.search(r'(?:Invoice\s*(?:#|No|Number|ID)?[:\s]+)([A-Za-z0-9\-_/]+)', full_text, re.IGNORECASE)
    inv_number = inv_num_match.group(1).strip() if inv_num_match else None

    # Fallback to general pattern if not found
    if not inv_number:
        inv_num_match = re.search(r'([A-Z]{2,4}-\d{4,8})', full_text)
        inv_number = inv_num_match.group(1).strip() if inv_num_match else f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Check duplicate
    existing = db.query(Invoice).filter(Invoice.invoice_number == inv_number).first()
    if existing:
        return 0, 1, [inv_number], [f"Invoice {inv_number} already exists in database."]

    # Customer Name
    customer_match = re.search(r'(?:Bill\s*To|Billed\s*To|Customer|Client)[:\s]+([^\n\r]+)', full_text, re.IGNORECASE)
    customer_name = customer_match.group(1).strip() if customer_match else "Customer (from PDF)"

    # Dates
    date_matches = re.findall(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})', full_text)
    inv_date = parse_date_safe(date_matches[0]) if date_matches else date.today()
    due_date = parse_date_safe(date_matches[1]) if len(date_matches) > 1 else (inv_date + timedelta(days=30))

    # Total Amount
    total_match = re.search(r'(?:Total\s*(?:Amount|Due)?|Grand\s*Total|Balance\s*Due)[:\s]*\$?\s*([0-9,]+\.[0-9]{2})', full_text, re.IGNORECASE)
    if total_match:
        total_amount = parse_float_safe(total_match.group(1))
    else:
        # Fallback to largest dollar amount found
        amounts = [parse_float_safe(m) for m in re.findall(r'\$([0-9,]+\.[0-9]{2})', full_text)]
        total_amount = max(amounts) if amounts else 100.0

    # Tax Amount
    tax_match = re.search(r'(?:Tax|VAT|GST)[:\s]*\$?\s*([0-9,]+\.[0-9]{2})', full_text, re.IGNORECASE)
    tax_amount = parse_float_safe(tax_match.group(1)) if tax_match else 0.0

    # Description
    desc_match = re.search(r'(?:Description|Item|Subject)[:\s]+([^\n\r]+)', full_text, re.IGNORECASE)
    desc = desc_match.group(1).strip() if desc_match else f"Extracted invoice {inv_number} from {filename}"

    status = InvoiceStatus.UNPAID.value
    if due_date < date.today():
        status = InvoiceStatus.OVERDUE.value

    invoice = Invoice(
        invoice_number=inv_number,
        customer_name=customer_name,
        invoice_date=inv_date,
        due_date=due_date,
        total_amount=round(total_amount, 2),
        paid_amount=0.0,
        remaining_amount=round(total_amount, 2),
        tax_amount=round(tax_amount, 2),
        currency="USD",
        description=desc,
        status=status,
        import_source="PDF",
        import_filename=filename
    )

    db.add(invoice)
    db.commit()
    log_audit(
        db,
        action="INVOICE_IMPORT_PDF",
        entity_type="INVOICE",
        entity_id=invoice.id,
        description=f"Imported invoice {inv_number} from PDF {filename}",
        details={"invoice_number": inv_number, "customer": customer_name, "total": total_amount},
        user_id=user_id
    )
    db.commit()

    return 1, 0, [], []
