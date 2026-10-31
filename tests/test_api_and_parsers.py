import pytest
import io
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pandas as pd

from app.database import Base
from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.reconciliation import ReconciliationSetting
from app.services.invoice_parser import parse_invoices_tabular, parse_invoice_pdf
from app.services.payment_parser import parse_bank_statement
from app.services.report_generator import generate_excel_report, generate_pdf_report

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    setting = ReconciliationSetting()
    session.add(setting)
    session.commit()

    yield session
    session.close()

def test_invoice_csv_import_and_duplicate_prevention(db_session):
    """Test CSV invoice import and duplicate prevention mechanism."""
    csv_content = (
        "invoice_number,customer_name,invoice_date,due_date,total_amount,currency\n"
        "INV-CSV-01,Test Corp,2026-10-01,2026-10-31,2500.00,USD\n"
        "INV-CSV-02,Test Corp,2026-10-02,2026-11-01,3500.00,USD\n"
    ).encode("utf-8")

    imported, skipped, dups, errs = parse_invoices_tabular(csv_content, "test.csv", db_session)
    assert imported == 2
    assert skipped == 0
    assert db_session.query(Invoice).count() == 2

    # Second import with the same CSV content: must skip both duplicates!
    imported2, skipped2, dups2, errs2 = parse_invoices_tabular(csv_content, "test.csv", db_session)
    assert imported2 == 0
    assert skipped2 == 2
    assert "INV-CSV-01" in dups2
    assert "INV-CSV-02" in dups2
    assert db_session.query(Invoice).count() == 2

def test_bank_statement_import_credit_debit(db_session):
    """Test bank statement import with automated credit vs debit segregation and duplicate flags."""
    csv_content = (
        "transaction_reference,payment_date,amount,currency,payment_method,customer_name,bank_description,transaction_type\n"
        "TXN-CR-01,2026-10-01,5000.00,USD,Wire Transfer,Client A,Invoice settlement,CREDIT\n"
        "TXN-DR-01,2026-10-02,-40.00,USD,Bank Fee,,Monthly fee,DEBIT\n"
        "TXN-CR-02,2026-10-03,2000.00,USD,ACH,Client B,Services deposit,CREDIT\n"
    ).encode("utf-8")

    total, receipts, debits, dups, susp, errs = parse_bank_statement(csv_content, "bank.csv", db_session)
    assert total == 3
    assert receipts == 2
    assert debits == 1
    assert len(errs) == 0

    debit_payment = db_session.query(Payment).filter(Payment.transaction_reference == "TXN-DR-01").first()
    assert debit_payment.transaction_type == "DEBIT"
    assert debit_payment.status == "EXCLUDED"
    assert debit_payment.unallocated_amount == 0.0

def test_report_generation(db_session):
    """Test generating Excel and PDF report byte streams."""
    # Seed minimal data
    inv = Invoice(
        invoice_number="INV-REP-01",
        customer_name="Report Client",
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        total_amount=1000.0,
        paid_amount=0.0,
        remaining_amount=1000.0,
        status="UNPAID"
    )
    db_session.add(inv)
    db_session.commit()

    # Generate Excel
    excel_bytes = generate_excel_report(db_session)
    assert excel_bytes is not None
    assert len(excel_bytes) > 1000
    assert excel_bytes[:2] == b"PK"  # Zip archive header for .xlsx

    # Generate PDF reports
    for r_type in ["summary", "unmatched", "outstanding", "suspicious"]:
        pdf_bytes = generate_pdf_report(db_session, report_type=r_type)
        assert pdf_bytes is not None
        assert len(pdf_bytes) > 500
        assert pdf_bytes[:4] == b"%PDF"
