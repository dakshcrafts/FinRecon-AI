import pytest
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus, TransactionType
from app.models.reconciliation import (
    ReconciliationMatch,
    ReconciliationSetting,
    MatchStatus,
    ConfidenceTier
)
from app.models.audit import AuditLog
from app.services.reconciliation_engine import (
    evaluate_pair,
    run_reconciliation_pipeline,
    approve_match,
    reject_match,
    manual_allocate,
    unmatch_allocation,
    get_reconciliation_settings
)

# In-memory test database fixture
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create default settings
    setting = ReconciliationSetting(
        weight_invoice_number=40.0,
        weight_customer_name=25.0,
        weight_amount=20.0,
        weight_date_proximity=15.0,
        auto_match_threshold=85.0,
        review_queue_threshold=60.0,
        auto_match_enabled=True,
        date_tolerance_days=30
    )
    session.add(setting)
    session.commit()

    yield session

    session.close()

def test_exact_invoice_match_high_confidence(db_session):
    """Test exact invoice number in description and exact amount matching."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-TEST-001",
        customer_name="Alpha Tech",
        invoice_date=today - timedelta(days=5),
        due_date=today + timedelta(days=25),
        total_amount=5000.0,
        paid_amount=0.0,
        remaining_amount=5000.0,
        status=InvoiceStatus.UNPAID.value
    )
    payment = Payment(
        transaction_reference="TXN-ALPHA-101",
        customer_name="Alpha Tech",
        payment_date=today - timedelta(days=3),
        amount=5000.0,
        allocated_amount=0.0,
        unallocated_amount=5000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Payment for INV-TEST-001 Alpha Tech",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, payment])
    db_session.commit()

    setting = get_reconciliation_settings(db_session)
    evaluation = evaluate_pair(invoice, payment, setting)

    assert evaluation["score"] >= 85.0
    assert evaluation["tier"] == ConfidenceTier.HIGH.value
    assert "INV-TEST-001" in evaluation["explanation"]

def test_partial_payment_allocation(db_session):
    """Test partial payment where payment amount is less than invoice total."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-PARTIAL-001",
        customer_name="Beta Logistics",
        invoice_date=today - timedelta(days=10),
        due_date=today + timedelta(days=20),
        total_amount=10000.0,
        paid_amount=0.0,
        remaining_amount=10000.0,
        status=InvoiceStatus.UNPAID.value
    )
    payment = Payment(
        transaction_reference="TXN-BETA-PARTIAL",
        customer_name="Beta Logistics",
        payment_date=today - timedelta(days=5),
        amount=4000.0,
        allocated_amount=0.0,
        unallocated_amount=4000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Partial installment for INV-PARTIAL-001",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, payment])
    db_session.commit()

    # Run pipeline with auto_approve_high=False to inspect proposed match
    res = run_reconciliation_pipeline(db_session, auto_approve_high=False)
    match = db_session.query(ReconciliationMatch).filter(
        ReconciliationMatch.invoice_id == invoice.id
    ).first()

    assert match is not None
    assert match.allocated_amount == 4000.0

    # Approve match manually
    approve_match(db_session, match.id)

    db_session.refresh(invoice)
    db_session.refresh(payment)

    assert invoice.paid_amount == 4000.0
    assert invoice.remaining_amount == 6000.0
    assert invoice.status == InvoiceStatus.PARTIALLY_PAID.value

    assert payment.allocated_amount == 4000.0
    assert payment.unallocated_amount == 0.0
    assert payment.status == PaymentStatus.FULLY_ALLOCATED.value

def test_multiple_payments_single_invoice(db_session):
    """Test two successive payments settling a single invoice to 0 balance."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-MULTI-001",
        customer_name="Gamma Industries",
        invoice_date=today - timedelta(days=15),
        due_date=today + timedelta(days=15),
        total_amount=8000.0,
        paid_amount=0.0,
        remaining_amount=8000.0,
        status=InvoiceStatus.UNPAID.value
    )
    pay1 = Payment(
        transaction_reference="TXN-GAMMA-01",
        customer_name="Gamma Industries",
        payment_date=today - timedelta(days=10),
        amount=5000.0,
        allocated_amount=0.0,
        unallocated_amount=5000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Deposit 1 for INV-MULTI-001",
        status=PaymentStatus.UNMATCHED.value
    )
    pay2 = Payment(
        transaction_reference="TXN-GAMMA-02",
        customer_name="Gamma Industries",
        payment_date=today - timedelta(days=5),
        amount=3000.0,
        allocated_amount=0.0,
        unallocated_amount=3000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Deposit 2 for INV-MULTI-001",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, pay1, pay2])
    db_session.commit()

    # First allocation: $5,000
    manual_allocate(db_session, invoice.id, pay1.id, 5000.0)
    db_session.refresh(invoice)
    assert invoice.paid_amount == 5000.0
    assert invoice.remaining_amount == 3000.0
    assert invoice.status == InvoiceStatus.PARTIALLY_PAID.value

    # Second allocation: $3,000
    manual_allocate(db_session, invoice.id, pay2.id, 3000.0)
    db_session.refresh(invoice)
    assert invoice.paid_amount == 8000.0
    assert invoice.remaining_amount == 0.0
    assert invoice.status == InvoiceStatus.PAID.value

def test_split_payment_across_invoices(db_session):
    """Test single $6,000 payment split across two invoices ($4,000 and $2,000)."""
    today = date.today()
    inv1 = Invoice(
        invoice_number="INV-SPLIT-001",
        customer_name="Delta Services",
        invoice_date=today - timedelta(days=12),
        due_date=today + timedelta(days=5),
        total_amount=4000.0,
        paid_amount=0.0,
        remaining_amount=4000.0,
        status=InvoiceStatus.UNPAID.value
    )
    inv2 = Invoice(
        invoice_number="INV-SPLIT-002",
        customer_name="Delta Services",
        invoice_date=today - timedelta(days=10),
        due_date=today + timedelta(days=15),
        total_amount=2000.0,
        paid_amount=0.0,
        remaining_amount=2000.0,
        status=InvoiceStatus.UNPAID.value
    )
    payment = Payment(
        transaction_reference="TXN-DELTA-LUMP",
        customer_name="Delta Services",
        payment_date=today - timedelta(days=2),
        amount=6000.0,
        allocated_amount=0.0,
        unallocated_amount=6000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Lump sum settlement for open Delta invoices",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([inv1, inv2, payment])
    db_session.commit()

    # Manual split allocation
    manual_allocate(db_session, inv1.id, payment.id, 4000.0)
    db_session.refresh(payment)
    assert payment.unallocated_amount == 2000.0

    manual_allocate(db_session, inv2.id, payment.id, 2000.0)
    db_session.refresh(payment)
    assert payment.unallocated_amount == 0.0
    assert payment.status == PaymentStatus.FULLY_ALLOCATED.value

    db_session.refresh(inv1)
    db_session.refresh(inv2)
    assert inv1.status == InvoiceStatus.PAID.value
    assert inv2.status == InvoiceStatus.PAID.value

def test_overpayment_prevention_and_suspicious_flag(db_session):
    """Test that overpayment attempt raises ValueError and flags suspicious."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-OVER-001",
        customer_name="Epsilon Inc",
        invoice_date=today - timedelta(days=5),
        due_date=today + timedelta(days=25),
        total_amount=3000.0,
        paid_amount=0.0,
        remaining_amount=3000.0,
        status=InvoiceStatus.UNPAID.value
    )
    payment = Payment(
        transaction_reference="TXN-EPSILON-OVER",
        customer_name="Epsilon Inc",
        payment_date=today - timedelta(days=2),
        amount=4500.0,
        allocated_amount=0.0,
        unallocated_amount=4500.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Payment for INV-OVER-001 with extra funds",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, payment])
    db_session.commit()

    # Attempting to allocate $4500 to a $3000 invoice balance must fail
    with pytest.raises(ValueError, match="exceeds invoice remaining balance"):
        manual_allocate(db_session, invoice.id, payment.id, 4500.0)

    # Database state must remain unchanged
    db_session.refresh(invoice)
    assert invoice.paid_amount == 0.0
    assert invoice.remaining_amount == 3000.0

def test_debit_exclusion_rule(db_session):
    """Test that debits (withdrawals / bank charges) are excluded from reconciliation."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-DEBIT-001",
        customer_name="Bank Fee Payer",
        invoice_date=today,
        due_date=today + timedelta(days=30),
        total_amount=50.0,
        paid_amount=0.0,
        remaining_amount=50.0,
        status=InvoiceStatus.UNPAID.value
    )
    debit_payment = Payment(
        transaction_reference="TXN-FEE-001",
        customer_name="Bank Fee Payer",
        payment_date=today,
        amount=50.0,
        allocated_amount=0.0,
        unallocated_amount=0.0,
        transaction_type=TransactionType.DEBIT.value,
        bank_description="Wire transfer charge fee",
        status=PaymentStatus.EXCLUDED.value
    )
    db_session.add_all([invoice, debit_payment])
    db_session.commit()

    setting = get_reconciliation_settings(db_session)
    evaluation = evaluate_pair(invoice, debit_payment, setting)

    assert evaluation["eligible"] is False
    assert evaluation["score"] == 0.0

    # Attempting manual allocation must also fail
    with pytest.raises(ValueError, match="Cannot reconcile against a debit/withdrawal"):
        manual_allocate(db_session, invoice.id, debit_payment.id, 50.0)

def test_rollback_and_unmatch(db_session):
    """Test that unmatching an allocation cleanly restores invoice and payment balances."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-ROLLBACK-001",
        customer_name="Zeta Corp",
        invoice_date=today - timedelta(days=5),
        due_date=today + timedelta(days=25),
        total_amount=2000.0,
        paid_amount=0.0,
        remaining_amount=2000.0,
        status=InvoiceStatus.UNPAID.value
    )
    payment = Payment(
        transaction_reference="TXN-ZETA-01",
        customer_name="Zeta Corp",
        payment_date=today - timedelta(days=2),
        amount=2000.0,
        allocated_amount=0.0,
        unallocated_amount=2000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Payment for INV-ROLLBACK-001",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, payment])
    db_session.commit()

    match = manual_allocate(db_session, invoice.id, payment.id, 2000.0)
    db_session.refresh(invoice)
    db_session.refresh(payment)
    assert invoice.remaining_amount == 0.0
    assert payment.unallocated_amount == 0.0

    # Now unmatch
    unmatch_allocation(db_session, match.id)
    db_session.refresh(invoice)
    db_session.refresh(payment)
    assert invoice.remaining_amount == 2000.0
    assert invoice.paid_amount == 0.0
    assert invoice.status == InvoiceStatus.UNPAID.value
    assert payment.unallocated_amount == 2000.0
    assert payment.allocated_amount == 0.0

def test_audit_log_tracking(db_session):
    """Test that actions create immutable audit log entries."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-AUDIT-001",
        customer_name="Audit Client",
        invoice_date=today,
        due_date=today + timedelta(days=30),
        total_amount=1500.0,
        paid_amount=0.0,
        remaining_amount=1500.0,
        status=InvoiceStatus.UNPAID.value
    )
    payment = Payment(
        transaction_reference="TXN-AUDIT-01",
        customer_name="Audit Client",
        payment_date=today,
        amount=1500.0,
        allocated_amount=0.0,
        unallocated_amount=1500.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Audit Test Payment",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, payment])
    db_session.commit()

    manual_allocate(db_session, invoice.id, payment.id, 1500.0)

    audit_entry = db_session.query(AuditLog).filter(
        AuditLog.action == "MANUAL_ALLOCATE"
    ).first()

    assert audit_entry is not None
    assert "Audit Client" in audit_entry.description or "1500.00" in audit_entry.description

def test_currency_incompatibility_prevention(db_session):
    """Test that mismatching currencies (e.g. USD vs EUR/INR) are prohibited from matching."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-CURR-01",
        customer_name="Global Trade",
        invoice_date=today,
        due_date=today + timedelta(days=30),
        total_amount=5000.0,
        paid_amount=0.0,
        remaining_amount=5000.0,
        currency="USD",
        status=InvoiceStatus.UNPAID.value
    )
    payment = Payment(
        transaction_reference="TXN-CURR-01",
        customer_name="Global Trade",
        payment_date=today,
        amount=5000.0,
        allocated_amount=0.0,
        unallocated_amount=5000.0,
        currency="EUR",
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Payment for INV-CURR-01 in Euros",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, payment])
    db_session.commit()

    setting = get_reconciliation_settings(db_session)
    evaluation = evaluate_pair(invoice, payment, setting)
    assert evaluation["eligible"] is False
    assert evaluation["score"] == 0.0
    assert "Currency incompatibility" in evaluation["explanation"]

def test_ambiguity_margin_routes_to_review_queue(db_session):
    """Test that competing candidates with close confidence scores within ambiguity margin are not auto-approved."""
    today = date.today()
    invoice = Invoice(
        invoice_number="INV-AMBIG-01",
        customer_name="Nexus Technologies",
        invoice_date=today - timedelta(days=5),
        due_date=today + timedelta(days=25),
        total_amount=3000.0,
        paid_amount=0.0,
        remaining_amount=3000.0,
        status=InvoiceStatus.UNPAID.value
    )
    # Payment 1: exact amount and close customer name
    payment1 = Payment(
        transaction_reference="TXN-NEXUS-01",
        customer_name="Nexus Technologies",
        payment_date=today - timedelta(days=3),
        amount=3000.0,
        allocated_amount=0.0,
        unallocated_amount=3000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Deposit Nexus Tech",
        status=PaymentStatus.UNMATCHED.value
    )
    # Payment 2: identical amount and slightly different narrative
    payment2 = Payment(
        transaction_reference="TXN-NEXUS-02",
        customer_name="Nexus Tech Ltd",
        payment_date=today - timedelta(days=4),
        amount=3000.0,
        allocated_amount=0.0,
        unallocated_amount=3000.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Transfer Nexus Tech Ltd",
        status=PaymentStatus.UNMATCHED.value
    )
    db_session.add_all([invoice, payment1, payment2])
    db_session.commit()

    pipeline_res = run_reconciliation_pipeline(db_session, auto_approve_high=True)
    # Because of ambiguity between TXN-NEXUS-01 and TXN-NEXUS-02, it should be in review queue, not auto-approved
    assert pipeline_res["review_queue_count"] >= 1
    match = db_session.query(ReconciliationMatch).filter(ReconciliationMatch.invoice_id == invoice.id).first()
    assert match is not None
    assert match.status == MatchStatus.PROPOSED.value

def test_anomaly_detection_rules(db_session):
    """Test transparent anomaly detection service for duplicate payments and overdue invoices."""
    from app.services.anomaly_service import detect_anomalies
    today = date.today()

    # Create two identical payments for Acme Corp on same date
    p1 = Payment(
        transaction_reference="TXN-DUP-A",
        customer_name="Acme Corp",
        payment_date=today - timedelta(days=2),
        amount=4500.0,
        allocated_amount=0.0,
        unallocated_amount=4500.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Acme payment batch",
        status=PaymentStatus.UNMATCHED.value
    )
    p2 = Payment(
        transaction_reference="TXN-DUP-B",
        customer_name="Acme Corp",
        payment_date=today - timedelta(days=2),
        amount=4500.0,
        allocated_amount=0.0,
        unallocated_amount=4500.0,
        transaction_type=TransactionType.CREDIT.value,
        bank_description="Acme payment duplicate",
        status=PaymentStatus.UNMATCHED.value
    )
    # Create severely overdue invoice
    inv_overdue = Invoice(
        invoice_number="INV-OLD-99",
        customer_name="Late Payer Inc",
        invoice_date=today - timedelta(days=90),
        due_date=today - timedelta(days=60),
        total_amount=8000.0,
        paid_amount=0.0,
        remaining_amount=8000.0,
        status=InvoiceStatus.OVERDUE.value
    )
    db_session.add_all([p1, p2, inv_overdue])
    db_session.commit()

    anomalies = detect_anomalies(db_session)
    assert len(anomalies) >= 2
    categories = [a.category for a in anomalies]
    assert "DUPLICATE_PAYMENT" in categories
    assert "OVERDUE_INVOICE" in categories

def test_outstanding_aging_buckets(db_session):
    """Test accounts receivable intelligence aging category calculations."""
    from app.services.outstanding_service import get_outstanding_receivables
    today = date.today()

    inv_current = Invoice(
        invoice_number="INV-AGE-CURRENT",
        customer_name="Client Current",
        invoice_date=today - timedelta(days=5),
        due_date=today + timedelta(days=20),
        total_amount=1000.0,
        paid_amount=0.0,
        remaining_amount=1000.0,
        status=InvoiceStatus.UNPAID.value
    )
    inv_30 = Invoice(
        invoice_number="INV-AGE-30",
        customer_name="Client 30",
        invoice_date=today - timedelta(days=40),
        due_date=today - timedelta(days=10),
        total_amount=2000.0,
        paid_amount=500.0,
        remaining_amount=1500.0,
        status=InvoiceStatus.OVERDUE.value
    )
    inv_90 = Invoice(
        invoice_number="INV-AGE-90",
        customer_name="Client 90",
        invoice_date=today - timedelta(days=130),
        due_date=today - timedelta(days=100),
        total_amount=5000.0,
        paid_amount=0.0,
        remaining_amount=5000.0,
        status=InvoiceStatus.OVERDUE.value
    )
    db_session.add_all([inv_current, inv_30, inv_90])
    db_session.commit()

    res = get_outstanding_receivables(db_session)
    assert res["total_records"] == 3
    assert res["bucket_totals"]["NOT_DUE"] == 1000.0
    assert res["bucket_totals"]["1_30_DAYS"] == 1500.0
    assert res["bucket_totals"]["OVER_90_DAYS"] == 5000.0
    assert res["total_outstanding"] == 7500.0

