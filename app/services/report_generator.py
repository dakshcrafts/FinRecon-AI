import io
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus, TransactionType
from app.models.reconciliation import ReconciliationMatch, MatchStatus
from app.models.audit import AuditLog

def generate_excel_report(db: Session) -> bytes:
    """Generate comprehensive multi-tab Excel reconciliation ledger."""
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    navy_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    alert_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

    font_title = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_regular = Font(name="Calibri", size=10)

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # ---------------------------------------------------------
    # TAB 1: EXECUTIVE SUMMARY
    # ---------------------------------------------------------
    ws_sum = wb.create_sheet(title="Executive Summary")
    ws_sum.views.sheetView[0].showGridLines = True

    ws_sum.merge_cells("A1:E2")
    title_cell = ws_sum["A1"]
    title_cell.value = "GRIPHER – Intelligent Financial Reconciliation Ledger"
    title_cell.font = font_title
    title_cell.fill = navy_fill
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws_sum["A3"] = f"Generated On: {now_str}"
    ws_sum["A3"].font = font_bold

    # Summary metrics calculation
    invoices = db.query(Invoice).all()
    payments = db.query(Payment).all()
    matches = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.status.in_([MatchStatus.APPROVED.value, MatchStatus.MANUAL_ALLOCATED.value])
    ).all()

    tot_inv_count = len(invoices)
    tot_inv_amount = sum(inv.total_amount for inv in invoices)
    tot_inv_rem = sum(inv.remaining_amount for inv in invoices)
    tot_inv_paid = sum(inv.paid_amount for inv in invoices)

    receipt_payments = [p for p in payments if p.transaction_type == TransactionType.CREDIT.value]
    tot_pay_count = len(receipt_payments)
    tot_pay_amount = sum(p.amount for p in receipt_payments)
    tot_pay_alloc = sum(p.allocated_amount for p in receipt_payments)
    tot_pay_unalloc = sum(p.unallocated_amount for p in receipt_payments)

    recon_rate = (tot_pay_alloc / tot_pay_amount * 100.0) if tot_pay_amount > 0 else 0.0

    metrics = [
        ("Metric Description", "Count", "Amount ($)"),
        ("Total Invoices Ingested", tot_inv_count, tot_inv_amount),
        ("Total Invoices Fully Paid", sum(1 for i in invoices if i.status == InvoiceStatus.PAID.value), tot_inv_paid),
        ("Total Invoices Remaining Outstanding", sum(1 for i in invoices if i.remaining_amount > 0), tot_inv_rem),
        ("Total Incoming Payment Receipts", tot_pay_count, tot_pay_amount),
        ("Reconciled / Allocated Payments", len(matches), tot_pay_alloc),
        ("Unmatched / Unallocated Receipts", sum(1 for p in receipt_payments if p.unallocated_amount > 0.01), tot_pay_unalloc),
        ("Reconciliation Progress Rate", f"{recon_rate:.1f}%", f"{tot_pay_alloc:,.2f} / {tot_pay_amount:,.2f}")
    ]

    for r_idx, row in enumerate(metrics, start=5):
        for c_idx, val in enumerate(row, start=1):
            cell = ws_sum.cell(row=r_idx, column=c_idx, value=val)
            cell.border = thin_border
            if r_idx == 5:
                cell.font = font_header
                cell.fill = header_fill
            else:
                cell.font = font_bold if c_idx == 1 else font_regular
                if isinstance(val, float):
                    cell.number_format = '$#,##0.00'

    # ---------------------------------------------------------
    # TAB 2: RECONCILED MATCHES
    # ---------------------------------------------------------
    ws_matches = wb.create_sheet(title="Reconciled Matches")
    match_headers = [
        "Match ID", "Invoice #", "Customer Name", "Payment Ref", "Allocated ($)",
        "Confidence Score", "Status", "Strategy Applied", "Approved At"
    ]
    ws_matches.append(match_headers)
    for col_idx in range(1, len(match_headers) + 1):
        cell = ws_matches.cell(row=1, column=col_idx)
        cell.font = font_header
        cell.fill = header_fill

    for m in matches:
        inv = m.invoice
        pay = m.payment
        row_vals = [
            m.id,
            inv.invoice_number if inv else "N/A",
            inv.customer_name if inv else "N/A",
            pay.transaction_reference if pay else "N/A",
            m.allocated_amount,
            f"{m.confidence_score:.1f}%",
            m.status,
            m.strategy_applied,
            m.approved_at.strftime("%Y-%m-%d %H:%M") if m.approved_at else "Auto"
        ]
        ws_matches.append(row_vals)
        r = ws_matches.max_row
        ws_matches.cell(row=r, column=5).number_format = '$#,##0.00'

    # ---------------------------------------------------------
    # TAB 3: UNMATCHED INVOICES
    # ---------------------------------------------------------
    ws_open_inv = wb.create_sheet(title="Unmatched Invoices")
    inv_headers = ["Invoice #", "Customer Name", "Invoice Date", "Due Date", "Total ($)", "Paid ($)", "Remaining ($)", "Status"]
    ws_open_inv.append(inv_headers)
    for c in range(1, len(inv_headers) + 1):
        ws_open_inv.cell(row=1, column=c).fill = header_fill
        ws_open_inv.cell(row=1, column=c).font = font_header

    unmatched_invoices = [i for i in invoices if i.remaining_amount > 0.01]
    for inv in unmatched_invoices:
        ws_open_inv.append([
            inv.invoice_number,
            inv.customer_name,
            str(inv.invoice_date),
            str(inv.due_date),
            inv.total_amount,
            inv.paid_amount,
            inv.remaining_amount,
            inv.status
        ])
        r = ws_open_inv.max_row
        ws_open_inv.cell(row=r, column=5).number_format = '$#,##0.00'
        ws_open_inv.cell(row=r, column=6).number_format = '$#,##0.00'
        ws_open_inv.cell(row=r, column=7).number_format = '$#,##0.00'

    # ---------------------------------------------------------
    # TAB 4: UNMATCHED PAYMENTS
    # ---------------------------------------------------------
    ws_open_pay = wb.create_sheet(title="Unmatched Payments")
    pay_headers = ["Reference", "Customer", "Date", "Total ($)", "Allocated ($)", "Unallocated ($)", "Type", "Status", "Bank Narrative"]
    ws_open_pay.append(pay_headers)
    for c in range(1, len(pay_headers) + 1):
        ws_open_pay.cell(row=1, column=c).fill = header_fill
        ws_open_pay.cell(row=1, column=c).font = font_header

    unmatched_payments = [p for p in payments if p.unallocated_amount > 0.01 or p.status == PaymentStatus.SUSPICIOUS.value]
    for p in unmatched_payments:
        ws_open_pay.append([
            p.transaction_reference,
            p.customer_name or "N/A",
            str(p.payment_date),
            p.amount,
            p.allocated_amount,
            p.unallocated_amount,
            p.transaction_type,
            p.status,
            p.bank_description
        ])
        r = ws_open_pay.max_row
        ws_open_pay.cell(row=r, column=4).number_format = '$#,##0.00'
        ws_open_pay.cell(row=r, column=5).number_format = '$#,##0.00'
        ws_open_pay.cell(row=r, column=6).number_format = '$#,##0.00'

    # ---------------------------------------------------------
    # TAB 5: SUSPICIOUS & DUPLICATE FLAGS
    # ---------------------------------------------------------
    ws_susp = wb.create_sheet(title="Suspicious & Duplicates")
    susp_headers = ["Reference", "Customer", "Date", "Amount ($)", "Reason", "Status"]
    ws_susp.append(susp_headers)
    for c in range(1, len(susp_headers) + 1):
        ws_susp.cell(row=1, column=c).fill = header_fill
        ws_susp.cell(row=1, column=c).font = font_header

    susp_payments = [p for p in payments if p.is_suspicious or p.is_duplicate or p.status == PaymentStatus.SUSPICIOUS.value]
    for p in susp_payments:
        ws_susp.append([
            p.transaction_reference,
            p.customer_name or "N/A",
            str(p.payment_date),
            p.amount,
            p.suspicion_reason or "Flagged as suspicious candidate",
            p.status
        ])
        r = ws_susp.max_row
        ws_susp.cell(row=r, column=4).number_format = '$#,##0.00'
        for col_idx in range(1, len(susp_headers) + 1):
            ws_susp.cell(row=r, column=col_idx).fill = alert_fill

    # Auto-adjust column widths across all sheets
    for sheet in wb.worksheets:
        sheet.views.sheetView[0].showGridLines = True
        for col in sheet.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or '')
                if '\n' in val_str:
                    val_str = max(val_str.split('\n'), key=len)
                max_len = max(max_len, len(val_str))
            sheet.column_dimensions[col_letter].width = min(40, max(max_len + 3, 12))

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def generate_pdf_report(db: Session, report_type: str = "summary") -> bytes:
    """Generate professional PDF reports using ReportLab."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#64748B'),
        spaceAfter=15
    )
    heading2_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=12,
        spaceAfter=8
    )
    cell_style = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#334155')
    )
    header_cell_style = ParagraphStyle(
        'HeaderCellText',
        parent=styles['Normal'],
        fontSize=8,
        leading=10,
        fontName='Helvetica-Bold',
        textColor=colors.white
    )

    elements = []
    now_str = datetime.now().strftime("%B %d, %Y - %H:%M:%S")

    # Header
    elements.append(Paragraph("<b>Gripher</b> – Intelligent Financial Reconciliation Platform", title_style))
    report_title_map = {
        "summary": "Executive Reconciliation Summary",
        "unmatched": "Unmatched Invoices & Payment Discrepancies",
        "outstanding": "Accounts Receivable Aging & Outstanding Balances",
        "suspicious": "Duplicate & Suspicious Transactions Audit",
        "discrepancies": "Discrepancy & Anomaly Detection Findings",
        "audit": "Immutable System Governance & Audit Trail"
    }
    elements.append(Paragraph(f"<b>Report Type:</b> {report_title_map.get(report_type, 'Summary')} | <b>Generated:</b> {now_str}", subtitle_style))
    elements.append(Spacer(1, 10))

    if report_type in ["summary", "outstanding"]:
        elements.append(Paragraph("Executive Key Metrics", heading2_style))
        invoices = db.query(Invoice).all()
        payments = db.query(Payment).filter(Payment.transaction_type == TransactionType.CREDIT.value).all()
        
        tot_inv_amt = sum(i.total_amount for i in invoices)
        tot_inv_rem = sum(i.remaining_amount for i in invoices)
        tot_pay_amt = sum(p.amount for p in payments)
        tot_pay_alloc = sum(p.allocated_amount for p in payments)
        rate = (tot_pay_alloc / tot_pay_amt * 100.0) if tot_pay_amt > 0 else 0.0

        summary_data = [
            [Paragraph("<b>Metric</b>", header_cell_style), Paragraph("<b>Value</b>", header_cell_style)],
            [Paragraph("Total Invoiced Amount", cell_style), Paragraph(f"${tot_inv_amt:,.2f}", cell_style)],
            [Paragraph("Total Outstanding Receivables", cell_style), Paragraph(f"${tot_inv_rem:,.2f}", cell_style)],
            [Paragraph("Total Payments Received (Credit)", cell_style), Paragraph(f"${tot_pay_amt:,.2f}", cell_style)],
            [Paragraph("Total Reconciled / Settled", cell_style), Paragraph(f"${tot_pay_alloc:,.2f}", cell_style)],
            [Paragraph("Reconciliation Settlement Rate", cell_style), Paragraph(f"{rate:.1f}%", cell_style)]
        ]
        t_summary = Table(summary_data, colWidths=[270, 270])
        t_summary.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(t_summary)
        elements.append(Spacer(1, 15))

    if report_type in ["summary", "unmatched"]:
        elements.append(Paragraph("Unmatched Open Invoices", heading2_style))
        open_invoices = db.query(Invoice).filter(Invoice.remaining_amount > 0.01).order_by(Invoice.due_date.asc()).limit(30).all()
        
        inv_data = [[
            Paragraph("<b>Invoice #</b>", header_cell_style),
            Paragraph("<b>Customer</b>", header_cell_style),
            Paragraph("<b>Due Date</b>", header_cell_style),
            Paragraph("<b>Total</b>", header_cell_style),
            Paragraph("<b>Remaining</b>", header_cell_style),
            Paragraph("<b>Status</b>", header_cell_style),
        ]]
        for inv in open_invoices:
            inv_data.append([
                Paragraph(inv.invoice_number, cell_style),
                Paragraph(inv.customer_name[:20], cell_style),
                Paragraph(str(inv.due_date), cell_style),
                Paragraph(f"${inv.total_amount:,.2f}", cell_style),
                Paragraph(f"${inv.remaining_amount:,.2f}", cell_style),
                Paragraph(inv.status, cell_style),
            ])
        t_inv = Table(inv_data, colWidths=[90, 130, 80, 80, 80, 80])
        t_inv.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563EB')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t_inv)
        elements.append(Spacer(1, 15))

    if report_type in ["summary", "suspicious"]:
        elements.append(Paragraph("Suspicious Transactions & Potential Duplicates", heading2_style))
        susp_payments = db.query(Payment).filter(
            (Payment.is_suspicious == True) | (Payment.is_duplicate == True) | (Payment.status == PaymentStatus.SUSPICIOUS.value)
        ).all()

        susp_data = [[
            Paragraph("<b>Reference</b>", header_cell_style),
            Paragraph("<b>Customer</b>", header_cell_style),
            Paragraph("<b>Date</b>", header_cell_style),
            Paragraph("<b>Amount</b>", header_cell_style),
            Paragraph("<b>Suspicion Reason / Review Note</b>", header_cell_style),
        ]]
        if not susp_payments:
            susp_data.append([
                Paragraph("None", cell_style),
                Paragraph("No suspicious transactions detected.", cell_style),
                Paragraph("-", cell_style),
                Paragraph("$0.00", cell_style),
                Paragraph("Clean audit status.", cell_style)
            ])
        else:
            for p in susp_payments:
                susp_data.append([
                    Paragraph(p.transaction_reference, cell_style),
                    Paragraph((p.customer_name or "N/A")[:18], cell_style),
                    Paragraph(str(p.payment_date), cell_style),
                    Paragraph(f"${p.amount:,.2f}", cell_style),
                    Paragraph(p.suspicion_reason or "Flagged as suspicious candidate, needs review", cell_style),
                ])
        t_susp = Table(susp_data, colWidths=[100, 100, 70, 70, 200])
        t_susp.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC2626')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FEF2F2')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t_susp)

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
