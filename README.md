# GRIPHER – Intelligent Financial Reconciliation Platform
### Hackathon Edition (PS02 – Invoice & Payment Reconciliation)

**GRIPHER** is a comprehensive, production-grade financial reconciliation platform engineered for Windows 10/11 desktops and enterprise deployment. It automatically matches invoices with bank and payment transactions, detects subtle financial discrepancies and fraud indicators, supports partial and split payments, transparently explains all matching decisions with AI scoring, and generates auditable PDF and Excel reports.

Built with **Python 3.11+ / 3.14**, **PySide6 (Qt for Python)**, **FastAPI**, **SQLAlchemy**, **SQLite**, **RapidFuzz**, **pypdf / PyMuPDF**, **ReportLab**, and **OpenPyXL**.

---

## 🌟 Key Features

1. **Native Desktop Experience (`Gripher.exe`)**
   - Single-click desktop application built with PySide6 and packaged via PyInstaller.
   - Built-in headless backend lifecycle management: dynamic port allocation, readiness polling, single-instance mutex (`Global\GripherSingleInstanceMutex`), and clean subprocess/thread shutdown.
   - Per-user writable data directory (`%LOCALAPPDATA%\Gripher`) ensuring database safety when installed in read-only folders (`Program Files`).

2. **Executive Real-time Dashboard**
   - 8 Operational KPI metrics dynamically calculated from live database records:
     - Total Invoices Value
     - Total Payments Received
     - Successfully Reconciled Amount
     - Outstanding Invoice Balance
     - Unmatched Transactions Count
     - Pending Review Count
     - Duplicate & Discrepancy Alerts
     - Reconciliation Rate (%)
   - Interactive Chart.js analytics: Reconciled vs Unreconciled, Monthly Invoices vs Inflows, Aging Buckets, and Discrepancy Breakdown.
   - 1-Click Interactive Demo Mode: resets and populates realistic multi-currency test scenarios.

3. **Multi-Format Ingestion Engine**
   - Invoices: **CSV**, **Excel (.xlsx, .xls)**, and **PDF** (layout-aware text extraction with OCR fallback).
   - Bank Statements: **CSV** and **Excel** with strict **Credit vs Debit Segregation**.
   - Debit amounts (bank fees, outgoing transfers) are safely excluded from matching candidates.
   - Duplicate import detection prevents re-inserting existing invoice numbers or bank transaction IDs.

4. **Intelligent Reconciliation Engine**
   - **Integer Minor Currency Units (Cents)**: all calculations execute using exact integer cents and Decimal arithmetic, preventing floating-point precision drift.
   - **Strict Currency Incompatibility Safeguard**: invoices and payments in different currencies (e.g., INR vs USD) are never auto-matched without explicit multi-currency conversion.
   - **Ambiguity Margin Detection**: when top two matching candidates are within the configured margin threshold, decisions are demoted to human review to prevent erroneous auto-allocation.
   - **Partial & Split Payment Allocation**:
     - Multiple payments against one invoice.
     - Single payment split across multiple invoices.
     - Overpayment guard strictly prohibiting allocations exceeding remaining balances.
   - **Multi-tiered Scoring**: Exact references, RapidFuzz entity similarity on customer names, exact amount matching, and proximity date tolerance.
   - **ACID Database Transactions**: atomic ledger allocation with automatic rollback on collision.

5. **Discrepancy & Anomaly Intelligence Center**
   - Dedicated anomaly engine scanning for:
     - `DUPLICATE_PAYMENT`: identical amounts, dates, or customer accounts.
     - `DUPLICATE_INVOICE`: recurring or duplicated invoice claims.
     - `OVERPAYMENT`: payments exceeding original invoice claims.
     - `UNMATCHED_PAYMENT`: aged unallocated funds.
     - `OVERDUE_INVOICE`: unpaid invoices past due dates.
     - `CURRENCY_MISMATCH`: mismatch between payment and invoice denominations.
     - `UNUSUAL_AMOUNT`: statistically outlying transactions.
     - `DATE_INCONSISTENCY`: payment received prior to invoice issuance date.
   - Resolve, dismiss, or escalate anomalies directly from the dashboard.

6. **Accounts Receivable Outstanding & Aging Analysis**
   - Standard 5-tier financial aging schedule:
     - `Current (Not Due)`
     - `1 – 30 Days Overdue`
     - `31 – 60 Days Overdue`
     - `61 – 90 Days Overdue`
     - `Over 90 Days (Delinquent)`
   - Filter by customer, currency, and aging bracket with exportable ledger breakdowns.

7. **Interactive Human-in-the-Loop Review Queue**
   - Filter by High Confidence, Medium Confidence, Suspicious/Alerts, Approved, and Rejected.
   - Detailed justification view showing score breakdown, similarity ratio, and date variance.
   - 1-Click Approve, Reject with reason, Rollback/Unmatch, or Manual Allocation modal.

8. **Enterprise Reporting & Exporting**
   - **Formatted Excel Master Ledger (.xlsx)**: multi-tab workbook with Summary, Reconciled Pairs, Outstanding Invoices, Unmatched Payments, and Audit Trail.
   - **Vector PDF Financial Reports**: generated via ReportLab with executive tables and charts.

9. **Security, Governance & Audit Trail**
   - Direct `bcrypt` password hashing and secure PyJWT token generation.
   - Immutable audit logging for every single action: imports, matches, approvals, rejections, manual splits, and rollbacks.

---

## 💻 Desktop Application Architecture

```
+-------------------------------------------------------------------+
|                        GRIPHER.EXE (PySide6)                      |
|                                                                   |
|   +-----------------------+     +-------------------------------+ |
|   |   desktop_run.py      |     |  Single-Instance Mutex Lock   | |
|   +-----------+-----------+     +-------------------------------+ |
|               |                                                   |
|   +-----------v-----------+     +-------------------------------+ |
|   |  desktop/app.py       |---->|  Dynamic Free Port Allocator  | |
|   +-----------+-----------+     +-------------------------------+ |
|               |                                                   |
|   +-----------v-----------+     +-------------------------------+ |
|   | desktop/splash.py     |---->|  Splash Screen & Health Check | |
|   +-----------+-----------+     +-------------------------------+ |
|               |                                                   |
|   +-----------v-----------+     +-------------------------------+ |
|   | desktop/server_thread |---->|  Uvicorn FastAPI Server       | |
|   +-----------+-----------+     |  (Bound to 127.0.0.1:port)     | |
|               |                 +---------------+---------------+ |
|               |                                 |                 |
|   +-----------v---------------------+           |                 |
|   | desktop/main_window.py          |           |                 |
|   | (PySide6 QWebEngineView Window) <-----------+                 |
|   +---------------------------------+                             |
|                                                                   |
|   +-------------------------------------------------------------+ |
|   | Storage: %LOCALAPPDATA%\Gripher\finrecon.db (ACID SQLite)   | |
+---+-------------------------------------------------------------+-+
```

---

## 🚀 Quick Start Guide

### Option 1: Run Pre-Built Executable (`Gripher.exe`)
1. Download or locate `dist\Gripher\Gripher.exe`.
2. Double-click `Gripher.exe`.
3. The splash screen will initialize the backend service, verify the local database, and launch the native desktop window.
4. Default credentials (or create your own):
   - **Username**: `admin`
   - **Password**: `admin123`

---

### Option 2: Run in Development Mode
Ensure Python 3.11+ is installed.

```powershell
# 1. Clone repository
git clone https://github.com/dakshcrafts/FinRecon-AI.git
cd FinRecon-AI

# 2. Run automated dev launcher (creates .venv, installs requirements, launches app)
.\scripts\run_dev.ps1
```

Or manually:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python desktop_run.py
```

To run purely as a local web service (without PySide6 desktop window):
```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Navigate to `http://127.0.0.1:8000`.

---

## 🧪 Automated Test Suite

Run the full automated test suite covering unit, parser, reconciliation engine, and desktop smoke tests:

```powershell
.\scripts\run_tests.ps1
```

Or with `pytest`:
```powershell
.\.venv\Scripts\pytest -v tests/
```

### Test Coverage Highlights:
- `tests/test_api_and_parsers.py`: Invoices/payments CRUD, CSV/Excel parser alias matching, duplicate checks, audit logging.
- `tests/test_reconciliation.py`: Exact matching, RapidFuzz tolerance, partial payments, split payments, multi-currency prevention, integer minor cents precision.
- `tests/test_desktop_smoke.py`: Port allocator, single-instance mutex, database backup and reset, desktop initialization.

---

## 🔨 Building the Windows Executable

To build the standalone Windows binary:

```powershell
.\scripts\build_windows.ps1
```

Verify the build output:
```powershell
.\scripts\verify_build.ps1
```

The output will be generated at:
`dist\Gripher\Gripher.exe`

---

## 📂 Project Directory Structure

```
FinRecon-AI/
├── app/
│   ├── models/                # SQLAlchemy ORM models (Invoice, Payment, Reconciliation, Anomaly)
│   ├── routers/               # FastAPI route controllers (Dashboard, Review, Discrepancies, etc.)
│   ├── schemas/               # Pydantic validation schemas
│   ├── services/              # Core domain logic
│   │   ├── reconciliation_engine.py  # Precision integer-cent AI matching engine
│   │   ├── anomaly_service.py        # Discrepancy and fraud detection rules
│   │   ├── outstanding_service.py    # Accounts receivable aging schedule
│   │   ├── invoice_parser.py         # CSV, Excel, PDF parser with pure-python fallback
│   │   ├── payment_parser.py         # Bank statement credit/debit segregation
│   │   ├── report_service.py         # Excel and PDF report generation
│   │   └── audit_service.py          # Compliance audit trail
│   ├── static/                # CSS (dark fintech theme), JS, Chart.js, icons
│   ├── templates/             # Jinja2 HTML templates
│   ├── database.py            # SQLite connection, migration, backup, demo-reset
│   └── main.py                # FastAPI app initialization
├── desktop/                   # Native PySide6 Desktop Shell
│   ├── app.py                 # Application lifecycle, mutex, port allocation
│   ├── splash.py              # Splash screen with server health polling
│   ├── server_thread.py       # Controlled Uvicorn background thread
│   └── main_window.py         # PySide6 desktop window (QWebEngineView)
├── packaging/
│   └── gripher.spec           # PyInstaller build specification
├── sample_data/               # Realistic invoices, bank statements, and edge cases
├── scripts/
│   ├── run_dev.ps1            # Development runner
│   ├── run_tests.ps1          # Automated test execution
│   ├── build_windows.ps1      # PyInstaller packaging script
│   └── verify_build.ps1       # Executable verification script
├── tests/                     # Automated unit and integration test suite
├── desktop_run.py             # Desktop launcher entry point
├── requirements.txt           # Python package dependencies
└── README.md                  # Comprehensive documentation
```

---

## 👥 Hackathon Team & Acknowledgements
- **Team**: FinRecon AI / Gripher Team
- **Problem Statement**: PS02 – Intelligent Financial Reconciliation
- **Repository**: [https://github.com/dakshcrafts/FinRecon-AI](https://github.com/dakshcrafts/FinRecon-AI)
