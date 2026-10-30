import os
from datetime import date, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import pandas as pd

from app.config import settings
from app.database import SessionLocal, init_db
from app.models.user import User, UserRole
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus, TransactionType
from app.services.auth_service import hash_password
from app.services.reconciliation_engine import run_reconciliation_pipeline
from app.services.audit_service import log_audit

def seed_database():
    print("Initializing Database...")
    init_db()

    db = SessionLocal()
    try:
        print("Checking users...")
        # 1. Admin user
        admin = db.query(User).filter(User.email == "admin@finrecon.ai").first()
        if not admin:
            admin = User(
                email="admin@finrecon.ai",
                hashed_password=hash_password("Admin@123456"),
                full_name="Chief Financial Controller",
                role=UserRole.ADMIN.value,
                is_active=True
            )
            db.add(admin)

        # 2. Analyst user
        analyst = db.query(User).filter(User.email == "analyst@finrecon.ai").first()
        if not analyst:
            analyst = User(
                email="analyst@finrecon.ai",
                hashed_password=hash_password("User@123456"),
                full_name="Reconciliation Analyst",
                role=UserRole.USER.value,
                is_active=True
            )
            db.add(analyst)

        db.commit()

        # Check if invoices already exist
        if db.query(Invoice).count() == 0:
            print("Seeding sample invoices...")
            today = date.today()

            invoices_data = [
                # Exact match candidate
                {
                    "invoice_number": "INV-2026-001",
                    "customer_name": "Acme Corporation",
                    "customer_email": "billing@acme.com",
                    "invoice_date": today - timedelta(days=20),
                    "due_date": today + timedelta(days=10),
                    "total_amount": 12500.00,
                    "tax_amount": 1250.00,
                    "currency": "USD",
                    "description": "Enterprise Cloud Architecture Q3 Services",
                    "import_source": "Seed Data"
                },
                # Duplicate payment test invoice (overdue)
                {
                    "invoice_number": "INV-2026-002",
                    "customer_name": "Acme Corporation",
                    "customer_email": "billing@acme.com",
                    "invoice_date": today - timedelta(days=45),
                    "due_date": today - timedelta(days=15),
                    "total_amount": 3200.00,
                    "tax_amount": 320.00,
                    "currency": "USD",
                    "description": "DevOps Support & Maintenance Contract",
                    "import_source": "Seed Data"
                },
                # Fuzzy customer match candidate
                {
                    "invoice_number": "INV-2026-003",
                    "customer_name": "Global Logistics Inc",
                    "customer_email": "ap@globallogistics.com",
                    "invoice_date": today - timedelta(days=15),
                    "due_date": today + timedelta(days=15),
                    "total_amount": 8400.00,
                    "tax_amount": 700.00,
                    "currency": "USD",
                    "description": "Fleet Management Telematics System Integration",
                    "import_source": "Seed Data"
                },
                # Unpaid invoice for Global Logistics
                {
                    "invoice_number": "INV-2026-004",
                    "customer_name": "Global Logistics Inc",
                    "customer_email": "ap@globallogistics.com",
                    "invoice_date": today - timedelta(days=5),
                    "due_date": today + timedelta(days=25),
                    "total_amount": 4100.00,
                    "tax_amount": 350.00,
                    "currency": "USD",
                    "description": "Logistics Dispatch Portal License Renewal",
                    "import_source": "Seed Data"
                },
                # Partial payment test invoice
                {
                    "invoice_number": "INV-2026-005",
                    "customer_name": "TechCorp Solutions",
                    "customer_email": "finance@techcorp.io",
                    "invoice_date": today - timedelta(days=25),
                    "due_date": today + timedelta(days=5),
                    "total_amount": 15000.00,
                    "tax_amount": 1500.00,
                    "currency": "USD",
                    "description": "Custom ERP Implementation Phase II",
                    "import_source": "Seed Data"
                },
                # Split payment test invoices (Skyline Media)
                {
                    "invoice_number": "INV-2026-006",
                    "customer_name": "Skyline Media Group",
                    "customer_email": "accounts@skylinemedia.com",
                    "invoice_date": today - timedelta(days=18),
                    "due_date": today + timedelta(days=12),
                    "total_amount": 5000.00,
                    "tax_amount": 450.00,
                    "currency": "USD",
                    "description": "Digital Marketing Campaign Management",
                    "import_source": "Seed Data"
                },
                {
                    "invoice_number": "INV-2026-007",
                    "customer_name": "Skyline Media Group",
                    "customer_email": "accounts@skylinemedia.com",
                    "invoice_date": today - timedelta(days=10),
                    "due_date": today + timedelta(days=20),
                    "total_amount": 2500.00,
                    "tax_amount": 200.00,
                    "currency": "USD",
                    "description": "SEO Optimization & Content Strategy",
                    "import_source": "Seed Data"
                },
                # Overpayment candidate invoice
                {
                    "invoice_number": "INV-2026-008",
                    "customer_name": "Apex Innovations",
                    "customer_email": "treasury@apexinnov.com",
                    "invoice_date": today - timedelta(days=35),
                    "due_date": today - timedelta(days=5),
                    "total_amount": 7800.00,
                    "tax_amount": 650.00,
                    "currency": "USD",
                    "description": "Machine Learning Model Training Pipeline",
                    "import_source": "Seed Data"
                }
            ]

            for item in invoices_data:
                inv = Invoice(
                    invoice_number=item["invoice_number"],
                    customer_name=item["customer_name"],
                    customer_email=item["customer_email"],
                    invoice_date=item["invoice_date"],
                    due_date=item["due_date"],
                    total_amount=item["total_amount"],
                    paid_amount=0.0,
                    remaining_amount=item["total_amount"],
                    tax_amount=item["tax_amount"],
                    currency=item["currency"],
                    description=item["description"],
                    import_source=item["import_source"]
                )
                inv.update_status()
                db.add(inv)

            db.commit()
            print("Sample invoices inserted.")

        # Check if payments already exist
        if db.query(Payment).count() == 0:
            print("Seeding realistic bank statement payments...")
            today = date.today()

            payments_data = [
                # 1. Exact reference & amount match for INV-2026-001
                {
                    "transaction_reference": "TXN-WIRE-9001",
                    "customer_name": "Acme Corporation",
                    "payment_date": today - timedelta(days=12),
                    "amount": 12500.00,
                    "payment_method": "Wire Transfer",
                    "bank_description": "WIRE IN: INV-2026-001 ACME CORP CLOUD ARCHITECTURE",
                    "transaction_type": TransactionType.CREDIT.value
                },
                # 2. Partial payment for TechCorp (INV-2026-005, $15k)
                {
                    "transaction_reference": "TXN-ACH-9002",
                    "customer_name": "TechCorp Solutions",
                    "payment_date": today - timedelta(days=8),
                    "amount": 6000.00,
                    "payment_method": "ACH",
                    "bank_description": "ACH DEP TECHCORP SOLUTIONS PARTIAL SETTLEMENT INV-2026-005",
                    "transaction_type": TransactionType.CREDIT.value
                },
                # 3. Second payment for TechCorp (multiple payments to single invoice)
                {
                    "transaction_reference": "TXN-ACH-9003",
                    "customer_name": "TechCorp Solutions",
                    "payment_date": today - timedelta(days=2),
                    "amount": 4000.00,
                    "payment_method": "ACH",
                    "bank_description": "ACH DEP TECHCORP SOLUTIONS SECOND INSTALLMENT",
                    "transaction_type": TransactionType.CREDIT.value
                },
                # 4. Split payment candidate: $7,500 from Skyline Media (covers $5,000 + $2,500)
                {
                    "transaction_reference": "TXN-WIRE-9004",
                    "customer_name": "Skyline Media Group",
                    "payment_date": today - timedelta(days=6),
                    "amount": 7500.00,
                    "payment_method": "Wire Transfer",
                    "bank_description": "WIRE IN: SKYLINE MEDIA GROUP MULTIPLE ACCOUNTS CONSOLIDATED",
                    "transaction_type": TransactionType.CREDIT.value
                },
                # 5. Fuzzy customer name match: "Global Logistics Ltd" vs "Global Logistics Inc" ($8,400)
                {
                    "transaction_reference": "TXN-BANK-9005",
                    "customer_name": "Global Logistics Ltd",
                    "payment_date": today - timedelta(days=9),
                    "amount": 8400.00,
                    "payment_method": "Bank Transfer",
                    "bank_description": "TRANSFER FROM GLOBAL LOGISTICS LTD TELEMATICS",
                    "transaction_type": TransactionType.CREDIT.value
                },
                # 6. Excluded Debit / Withdrawal (Bank fees)
                {
                    "transaction_reference": "TXN-DEBIT-9006",
                    "customer_name": None,
                    "payment_date": today - timedelta(days=14),
                    "amount": 35.00,
                    "payment_method": "Bank Charge",
                    "bank_description": "MONTHLY INCOMING WIRE RECEIVING FEE",
                    "transaction_type": TransactionType.DEBIT.value
                },
                # 7. Excluded Debit / Vendor payout
                {
                    "transaction_reference": "TXN-DEBIT-9007",
                    "customer_name": "Office Supplies Co",
                    "payment_date": today - timedelta(days=11),
                    "amount": 450.00,
                    "payment_method": "Direct Debit",
                    "bank_description": "OUTGOING VENDOR PAYOUT FOR OFFICE SUPPLIES",
                    "transaction_type": TransactionType.DEBIT.value
                },
                # 8. Duplicate payment candidate (Same customer Acme, same amount $3,200 on same day)
                {
                    "transaction_reference": "TXN-CHK-9008",
                    "customer_name": "Acme Corporation",
                    "payment_date": today - timedelta(days=4),
                    "amount": 3200.00,
                    "payment_method": "Check",
                    "bank_description": "CHECK DEPOSIT ACME CORP INV-2026-002",
                    "transaction_type": TransactionType.CREDIT.value
                },
                {
                    "transaction_reference": "TXN-CHK-9009",
                    "customer_name": "Acme Corporation",
                    "payment_date": today - timedelta(days=4),
                    "amount": 3200.00,
                    "payment_method": "Check",
                    "bank_description": "CHECK DEPOSIT ACME CORP (POTENTIAL DUPLICATE RUN)",
                    "transaction_type": TransactionType.CREDIT.value,
                    "is_duplicate": True,
                    "is_suspicious": True,
                    "suspicion_reason": "Duplicate candidate: Identical amount $3,200 for Acme Corporation recorded within same batch."
                },
                # 9. Overpayment candidate ($9,000 payment for $7,800 invoice)
                {
                    "transaction_reference": "TXN-WIRE-9010",
                    "customer_name": "Apex Innovations",
                    "payment_date": today - timedelta(days=3),
                    "amount": 9000.00,
                    "payment_method": "Wire Transfer",
                    "bank_description": "WIRE IN: APEX INNOVATIONS INV-2026-008 SETTLEMENT",
                    "transaction_type": TransactionType.CREDIT.value,
                    "is_suspicious": True,
                    "suspicion_reason": "Overpayment candidate: Amount $9,000 exceeds invoice balance $7,800."
                }
            ]

            for p_data in payments_data:
                is_debit = p_data["transaction_type"] == TransactionType.DEBIT.value
                is_susp = p_data.get("is_suspicious", False)
                status_val = PaymentStatus.EXCLUDED.value if is_debit else (PaymentStatus.SUSPICIOUS.value if is_susp else PaymentStatus.UNMATCHED.value)

                payment = Payment(
                    transaction_reference=p_data["transaction_reference"],
                    customer_name=p_data["customer_name"],
                    payment_date=p_data["payment_date"],
                    amount=p_data["amount"],
                    allocated_amount=0.0,
                    unallocated_amount=0.0 if is_debit else p_data["amount"],
                    currency="USD",
                    payment_method=p_data["payment_method"],
                    bank_description=p_data["bank_description"],
                    transaction_type=p_data["transaction_type"],
                    import_source="Seed Bank Statement",
                    is_duplicate=p_data.get("is_duplicate", False),
                    is_suspicious=is_susp,
                    suspicion_reason=p_data.get("suspicion_reason"),
                    status=status_val
                )
                db.add(payment)

            db.commit()
            print("Realistic bank statement payments inserted.")

        # Run initial reconciliation pipeline to prepare high/medium matches and review queue!
        print("Executing initial AI reconciliation pipeline...")
        recon_result = run_reconciliation_pipeline(db, auto_approve_high=True, user_id=admin.id)
        print(f"Initial reconciliation complete: {recon_result}")

        # Generate sample test files in sample_files/
        generate_sample_files()

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()

def generate_sample_files():
    """Create sample CSV, Excel, and PDF files for immediate testing."""
    sample_dir = settings.SAMPLE_DIR
    sample_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # 1. Sample Invoices CSV
    inv_df = pd.DataFrame([
        {
            "invoice_number": "INV-2026-801",
            "customer_name": "Nexus Retail Corp",
            "customer_email": "ap@nexusretail.com",
            "invoice_date": (today - timedelta(days=10)).isoformat(),
            "due_date": (today + timedelta(days=20)).isoformat(),
            "total_amount": 14200.00,
            "tax_amount": 1200.00,
            "currency": "USD",
            "description": "E-Commerce Checkout Gateway Optimization"
        },
        {
            "invoice_number": "INV-2026-802",
            "customer_name": "Starlight Dynamics",
            "customer_email": "finance@starlight.io",
            "invoice_date": (today - timedelta(days=5)).isoformat(),
            "due_date": (today + timedelta(days=25)).isoformat(),
            "total_amount": 6750.00,
            "tax_amount": 550.00,
            "currency": "USD",
            "description": "Data Analytics Pipeline Implementation"
        }
    ])
    inv_csv_path = sample_dir / "sample_invoices_batch.csv"
    inv_df.to_csv(inv_csv_path, index=False)

    # 2. Sample Invoices Excel
    inv_xlsx_path = sample_dir / "sample_invoices_batch.xlsx"
    inv_df.to_excel(inv_xlsx_path, index=False)

    # 3. Sample PDF Invoice (Acme Corp)
    pdf_path = sample_dir / "sample_invoice_acme.pdf"
    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
    styles = getSampleStyleSheet()
    elems = [
        Paragraph("<b>INVOICE</b>", styles['Heading1']),
        Spacer(1, 12),
        Paragraph("<b>Invoice Number:</b> INV-2026-999", styles['Normal']),
        Paragraph("<b>Bill To:</b> Acme Corporation", styles['Normal']),
        Paragraph(f"<b>Invoice Date:</b> {today.isoformat()}", styles['Normal']),
        Paragraph(f"<b>Due Date:</b> {(today + timedelta(days=30)).isoformat()}", styles['Normal']),
        Spacer(1, 15),
        Paragraph("<b>Total Amount:</b> $18,500.00", styles['Heading2']),
        Paragraph("<b>Tax Amount:</b> $1,500.00", styles['Normal']),
        Paragraph("Description: Cloud Migration & Kubernetes Infrastructure Overhaul", styles['Normal'])
    ]
    doc.build(elems)

    # 4. Sample Bank Statement CSV
    stmt_df = pd.DataFrame([
        {
            "transaction_reference": "TXN-STMT-701",
            "payment_date": today.isoformat(),
            "amount": 14200.00,
            "currency": "USD",
            "payment_method": "Wire Transfer",
            "customer_name": "Nexus Retail Corp",
            "bank_description": "WIRE IN: INV-2026-801 NEXUS RETAIL GATEWAY",
            "transaction_type": "CREDIT"
        },
        {
            "transaction_reference": "TXN-STMT-702",
            "payment_date": today.isoformat(),
            "amount": -50.00,
            "currency": "USD",
            "payment_method": "Bank Fee",
            "customer_name": "",
            "bank_description": "INTERNATIONAL WIRE PROCESSING CHARGE",
            "transaction_type": "DEBIT"
        }
    ])
    stmt_csv_path = sample_dir / "sample_bank_statement.csv"
    stmt_df.to_csv(stmt_csv_path, index=False)

    # 5. Sample Bank Statement Excel
    stmt_xlsx_path = sample_dir / "sample_bank_statement.xlsx"
    stmt_df.to_excel(stmt_xlsx_path, index=False)

    print(f"Generated sample files in: {sample_dir}")

if __name__ == "__main__":
    seed_database()
