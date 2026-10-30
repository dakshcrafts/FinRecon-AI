# FinRecon AI – Intelligent Invoice & Payment Reconciliation Dashboard

**FinRecon AI** is a complete, production-grade, local enterprise application designed for intelligent invoice and payment reconciliation, built with **Python 3.11+**, **FastAPI**, **SQLAlchemy**, **SQLite**, **Bootstrap 5**, **Chart.js**, **RapidFuzz**, **PyMuPDF**, **ReportLab**, and **OpenPyXL**.

---

## 🌟 Key Features

1. **Enterprise Authentication & Access Control**
   - Direct `bcrypt` password hashing and secure PyJWT token generation.
   - Dual-mode authentication: HttpOnly cookie for seamless web browsing and Bearer header for API integration.
   - Role-Based Access Control (**Admin** and **User/Analyst** roles).

2. **Executive Real-time Dashboard**
   - KPI metrics dynamically calculated from SQLite: Total invoices, Payments received, Outstanding receivables, Reconciliation settlement rate %, Unmatched receipts, Overdue invoices, and Duplicate/Suspicious warnings.
   - Interactive Chart.js charts:
     - Monthly Invoice vs Payment comparison
     - Invoice status distribution (Paid, Partially Paid, Unpaid, Overdue)
     - Daily bank inflow trends
     - Top outstanding balances by debtor client
   - Quick action triggers: 1-click Auto-Reconciliation, Review Queue jump, and recent audit feed.

3. **Multi-Format Invoices Ingestion**
   - Ingest invoices via **CSV**, **Excel (.xlsx, .xls)**, and **PDF** (layout-aware text extraction with PyMuPDF).
   - Flexible column header alias resolution (e.g., `inv_no`, `Invoice #`, `Total Amount`, `Due Date`).
   - Automated duplicate-import prevention: skips already recorded invoice numbers and logs duplicate candidates.
   - Full CRUD: search, filter by date/status, view allocated payments breakdown, and delete safeguards.

4. **Payments & Bank Statement Segregation**
   - Bank statement ingestion (CSV and Excel) with strict **Credit vs Debit Segregation**.
   - Only incoming receipts (`CREDIT`) are eligible for reconciliation. Outgoing withdrawals, bank service fees, and debit transactions are segregated as `DEBIT (EXCLUDED)` and prevented from accidental allocation.
   - Duplicate payment detection: flags same customer + same amount + close dates as `"Duplicate payment candidate, needs review"`.

5. **AI Reconciliation Engine**
   - Multi-tiered strategy scoring:
     - Exact invoice number and transaction reference extraction
     - RapidFuzz entity similarity on customer names
     - Exact amount and remaining balance matching
     - Date proximity scoring within configurable tolerance window
   - Configurable normalized confidence score (0–100) using configurable weights.
   - Classification tiers:
     - **High** (&ge; 85%): Candidate for automated instant settlement
     - **Medium** (60% – 84%): Placed in human-in-the-loop Review Queue
     - **Low** (< 60%): Remains unmatched
     - **Suspicious**: Overpayment warnings and duplicate candidates flagged for compliance review (never auto-labels fraud; uses `"suspicious, needs review"`)
   - Advanced financial allocation logic:
     - **Partial payments**: receipts smaller than invoice balance partially settle invoices.
     - **Multiple payments per invoice**: successive deposits reduce remaining balance until settled.
     - **Split payment across invoices**: single lump-sum customer payment split across open customer invoices.
     - **Overpayment safeguard**: prevents allocating beyond remaining balance.
   - **ACID Transactions**: all allocations execute within database transactions with automated rollback on error.
   - Full human explanation generated for every proposed pair.

6. **Interactive Review Queue**
   - Filter tabs: Pending Review, High Confidence, Medium Confidence, Suspicious/Alerts, Approved Ledger, and Rejected.
   - Expandable breakdown showing score points for each criterion, customer similarity ratio, and date variance.
   - 1-Click Approve, Reject with justification, and Rollback/Unmatch.
   - **Manual Allocation / Split Modal**: pick an invoice and unallocated payment, enter a custom dollar amount with live preview of new remaining balances.
   - Bulk approval for high-confidence matches.

7. **Reports & Exports**
   - **Excel Master Ledger (.xlsx)**: multi-tab formatted workbook using OpenPyXL (Summary, Reconciled Pairs, Unmatched Invoices, Unmatched Payments, Suspicious & Duplicates, and Audit Trail).
   - **PDF Reports**: generated using ReportLab:
     - Executive Reconciliation Summary
     - Unmatched Invoices & Payment Discrepancies
     - Outstanding Balances by Customer
     - Suspicious Transactions & Duplicates Audit

8. **Governance & Audit Trail**
   - Immutable audit logging of all system actions: imports, matches, approvals, rejections, manual allocations, deletes, rollbacks, and settings updates.

---

## 🚀 Step-by-Step Windows Setup Guide

### Prerequisites
- Windows 10 / 11 / Server
- Python 3.11+ installed and added to `PATH`
- PowerShell or Windows Command Prompt

### Step 1: Open PowerShell in Project Directory
```powershell
cd "c:\Users\B2B LAPP HUB\Desktop\Hackaton\Project"
```

### Step 2: Create and Activate Virtual Environment
```powershell
# Create virtual environment (if not already created)
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies
```powershell
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy `.env.example` to `.env` (already created):
```powershell
copy .env.example .env
```

### Step 5: Initialize and Seed Realistic Demo Data
Run the seeding script to initialize SQLite tables, default users, invoices, bank statements, initial reconciliation matches, and sample test files:
```powershell
python seed.py
```

### Step 6: Run the Pytest Test Suite
Verify that all reconciliation rules, partial allocations, multiple payments, split payments, overpayment safeguards, debit exclusions, and audit logging pass:
```powershell
python -m pytest -v
```

### Step 7: Launch the Application Server
Start Uvicorn on localhost:
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser and navigate to:
👉 **`http://127.0.0.1:8000`**

---

## 🔑 Default Login Credentials

| Role | Email | Password | Access |
|---|---|---|---|
| **Administrator** | `admin@finrecon.ai` | `Admin@123456` | Full access: Engine configuration, weights tuning, approvals, manual allocations, exports, audit trail |
| **Analyst** | `analyst@finrecon.ai` | `User@123456` | Operations access: Review queue, invoices, payments, manual allocations, report downloads |

*(Tip: On the login page, click the **"Admin Demo"** or **"Analyst Demo"** buttons to auto-fill credentials instantly!)*

---

## 📁 Project Directory Structure

```
FinReconAI/
├── app/
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── user.py              # User & UserRole (ADMIN, USER)
│   │   ├── invoice.py           # Invoice & InvoiceStatus
│   │   ├── payment.py           # Payment, PaymentStatus & TransactionType (CREDIT, DEBIT)
│   │   ├── reconciliation.py    # ReconciliationMatch & ReconciliationSetting
│   │   └── audit.py             # AuditLog table
│   ├── schemas/                 # Pydantic v2 validation models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── invoice.py
│   │   ├── payment.py
│   │   ├── reconciliation.py
│   │   ├── dashboard.py
│   │   └── audit.py
│   ├── services/                # Business logic services
│   │   ├── auth_service.py      # bcrypt + PyJWT + FastAPI auth dependencies
│   │   ├── audit_service.py     # Centralized audit logging
│   │   ├── invoice_parser.py    # CSV, Excel, and PyMuPDF PDF parser
│   │   ├── payment_parser.py    # Bank statement CSV/Excel with credit/debit filter
│   │   ├── reconciliation_engine.py # Intelligent multi-pass scoring & allocations
│   │   └── report_generator.py  # ReportLab PDF & OpenPyXL Excel reports
│   ├── routers/                 # FastAPI HTTP & API routes
│   │   ├── auth.py              # Login, Register, Logout, Me
│   │   ├── dashboard.py         # Dashboard HTML & JSON metrics/charts
│   │   ├── invoices.py          # Invoices CRUD, search, filter, CSV/Excel/PDF upload
│   │   ├── payments.py          # Payments CRUD, search, filter, bank statement upload
│   │   ├── reconciliation.py    # Engine runner, review queue, approve, reject, manual split
│   │   ├── reports.py           # PDF and Excel downloads
│   │   ├── settings.py          # Admin weights and thresholds configuration
│   │   └── audit_logs.py        # Audit trail viewer
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── base.html            # Sidebar, topbar, theme, toast notifications
│   │   ├── login.html           # Branded login card with demo quick-fill
│   │   ├── register.html        # Registration page
│   │   ├── dashboard.html       # Executive KPI cards & Chart.js charts
│   │   ├── invoices.html        # Invoices data table, modal CRUD & import dropzone
│   │   ├── payments.html        # Payments data table & bank statement upload
│   │   ├── reconciliation.html  # Engine execution console & rule weights
│   │   ├── review_queue.html    # Review Queue with criteria accordion & manual split
│   │   ├── reports.html         # PDF & Excel export center
│   │   ├── settings.html        # Weight sliders & live preview simulator
│   │   └── audit_logs.html      # Governance audit trail & JSON inspector
│   ├── static/                  # Client-side static assets
│   │   ├── css/custom.css       # Design system tokens, badges, cards, tables
│   │   └── js/
│   │       ├── app.js           # Toast alerts, formatting, active nav
│   │       └── dashboard.js     # Chart.js initialization & auto-refresh
│   ├── config.py                # Pydantic BaseSettings & configuration
│   ├── database.py              # SQLite engine, WAL mode, sessionmaker & init_db
│   └── main.py                  # FastAPI application entry point & lifespan
├── tests/
│   ├── test_reconciliation.py   # Unit tests for partial, split, multi, overpayment, debits
│   └── test_api_and_parsers.py  # Tests for CSV/Excel/PDF parsing & reports
├── sample_files/                # Auto-generated sample files for testing
│   ├── sample_invoices_batch.csv
│   ├── sample_invoices_batch.xlsx
│   ├── sample_invoice_acme.pdf
│   ├── sample_bank_statement.csv
│   └── sample_bank_statement.xlsx
├── requirements.txt
├── pytest.ini
├── .env.example
├── .env
├── seed.py
└── README.md
```

---

## 🧪 Testing Reconciliation Rules

Run the automated test suite anytime with:
```powershell
python -m pytest -v
```

The 11 test cases thoroughly validate:
- **`test_exact_invoice_match_high_confidence`**: Verifies exact invoice numbers in bank narratives score &ge; 85% and qualify for high-confidence auto-approval.
- **`test_partial_payment_allocation`**: Verifies that smaller payments partially settle invoice balances, updating invoice status to `PARTIALLY_PAID` and payment to `FULLY_ALLOCATED`.
- **`test_multiple_payments_single_invoice`**: Verifies two separate installment payments reduce remaining invoice balance to zero and update status to `PAID`.
- **`test_split_payment_across_invoices`**: Verifies a single lump-sum customer payment splits across multiple open invoices.
- **`test_overpayment_prevention_and_suspicious_flag`**: Verifies that payments exceeding invoice balances cannot be blindly allocated, raising validation errors and preventing state corruption.
- **`test_debit_exclusion_rule`**: Verifies that withdrawals, bank fees, and outgoing charges (`DEBIT`) are excluded from reconciliation.
- **`test_rollback_and_unmatch`**: Verifies that unmatching an allocation reverts invoice and payment balances in an atomic transaction.
- **`test_audit_log_tracking`**: Verifies that every allocation, approval, and modification writes an immutable audit log.
- **`test_invoice_csv_import_and_duplicate_prevention`**: Verifies that re-importing the same invoice skips duplicates.
- **`test_bank_statement_import_credit_debit`**: Verifies statement credit/debit segregation.
- **`test_report_generation`**: Verifies valid PDF (`%PDF`) and Excel (`PK`) binary file generation.

---

## 📄 License
MIT License. Created for the Financial Reconciliation Hackathon 2026.
