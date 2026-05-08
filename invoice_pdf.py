"""SARS-compliant tax invoice PDF.

Layout intentionally matches the existing quote PDF (pdf_render.py) so the
brand is consistent. SARS requires a tax invoice for supplies > R5,000 (full)
or > R50 (abridged) to include:
  - The words "Tax Invoice"
  - Vendor name, address, VAT registration number
  - Customer name, address, VAT registration number (for full)
  - Serial invoice number
  - Date of issue
  - Description of goods/services
  - Quantity / volume of goods/services
  - Value (excluding VAT), VAT amount, total (incl VAT) — OR total + words
    "the price includes VAT"

Public function:
  render_invoice_pdf(invoice: dict, company: dict) -> bytes
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as _escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
INK = colors.black


def _esc(s) -> str:
    return _escape(str(s or ""), entities={'"': "&quot;", "'": "&apos;"})


def _styles():
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("Body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=10, textColor=INK, leading=12),
        "body_bold": ParagraphStyle("BodyB", parent=base["Normal"], fontName="Helvetica-Bold",
                                    fontSize=10, textColor=INK, leading=12),
        "body_right": ParagraphStyle("BodyR", parent=base["Normal"], fontName="Helvetica",
                                     fontSize=10, textColor=INK, alignment=2, leading=12),
        "title": ParagraphStyle("Title", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=18, textColor=INK, leading=22),
        "subtitle": ParagraphStyle("Sub", parent=base["Normal"], fontName="Helvetica",
                                   fontSize=11, textColor=INK, leading=14),
        "small": ParagraphStyle("Small", parent=base["Normal"], fontName="Helvetica",
                                fontSize=8, textColor=INK, leading=10),
        "small_bold": ParagraphStyle("SmallB", parent=base["Normal"], fontName="Helvetica-Bold",
                                     fontSize=8, textColor=INK, leading=10),
    }


def _money(v: float) -> str:
    try:
        return f"R {float(v):,.2f}"
    except (TypeError, ValueError):
        return "R 0.00"


def render_invoice_pdf(invoice: dict, company: dict) -> bytes:
    """Render a SARS-compliant tax invoice. invoice is the dict returned by
    invoices.get_invoice(); company is the dict from company_profile.load_profile()."""
    s = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title=f"Tax Invoice {invoice.get('invoice_no', '')}",
    )
    page_w = A4[0] - 36 * mm  # 174 mm usable

    story: list = []

    # ----- Top band: company block (left) + logo + TAX INVOICE label (right)
    company_block = []
    company_block.append(Paragraph(_esc(company.get("company_name") or "NDLOVU T PROJECTS (PTY) LTD"), s["body_bold"]))
    if company.get("company_address"):
        for line in str(company["company_address"]).split("\n"):
            if line.strip():
                company_block.append(Paragraph(_esc(line), s["body"]))
    if company.get("company_contact"):
        company_block.append(Paragraph(_esc(company["company_contact"]), s["body"]))
    vat_line = company.get("company_vat_reg")
    if vat_line:
        company_block.append(Paragraph(f"VAT Reg: {_esc(vat_line)}", s["body"]))

    right_block = []
    if LOGO_PATH.exists():
        try:
            logo = Image(str(LOGO_PATH), width=38 * mm, height=24 * mm)
            logo.hAlign = "RIGHT"
            right_block.append(logo)
        except Exception:
            pass
    right_block.append(Paragraph("TAX INVOICE", s["title"]))

    top_table = Table(
        [[company_block, right_block]],
        colWidths=[page_w * 0.55, page_w * 0.45],
        hAlign="LEFT",
    )
    top_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(top_table)
    story.append(Spacer(1, 6 * mm))

    # ----- Bill-to + invoice meta side-by-side
    bill_to = [Paragraph("<b>Invoice to:</b>", s["body_bold"])]
    bill_to.append(Paragraph(_esc(invoice.get("client_name") or ""), s["body_bold"]))
    if invoice.get("client_attention"):
        bill_to.append(Paragraph(f"Attention: {_esc(invoice['client_attention'])}", s["body"]))
    if invoice.get("client_address"):
        for line in str(invoice["client_address"]).split("\n"):
            if line.strip():
                bill_to.append(Paragraph(_esc(line), s["body"]))
    if invoice.get("client_vat_reg"):
        bill_to.append(Paragraph(f"VAT Reg: {_esc(invoice['client_vat_reg'])}", s["body"]))

    meta_rows = [
        ["Invoice No.", _esc(invoice.get("invoice_no", ""))],
        ["Invoice Date", _esc(invoice.get("invoice_date", ""))],
        ["Due Date", _esc(invoice.get("due_date", ""))],
    ]
    if invoice.get("project_name"):
        meta_rows.append(["Project", _esc(invoice["project_name"])])
    if invoice.get("re_subject"):
        meta_rows.append(["RE:", _esc(invoice["re_subject"])])
    if invoice.get("quote_id"):
        meta_rows.append(["Quote Ref", _esc(invoice["quote_id"])])

    meta_table = Table(meta_rows, colWidths=[28 * mm, 50 * mm])
    meta_table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    side_by_side = Table(
        [[bill_to, meta_table]],
        colWidths=[page_w * 0.55, page_w * 0.45],
    )
    side_by_side.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(side_by_side)
    story.append(Spacer(1, 6 * mm))

    # ----- Line items table
    header_row = [
        Paragraph("<b>Description</b>", s["body"]),
        Paragraph("<b>Qty</b>", s["body_right"]),
        Paragraph("<b>Unit</b>", s["body"]),
        Paragraph("<b>Rate</b>", s["body_right"]),
        Paragraph("<b>Amount</b>", s["body_right"]),
    ]
    rows = [header_row]
    for ln in invoice.get("lines", []):
        rows.append([
            Paragraph(_esc(ln.get("description", "")), s["body"]),
            Paragraph(f"{float(ln.get('quantity') or 0):g}", s["body_right"]),
            Paragraph(_esc(ln.get("unit") or "no"), s["body"]),
            Paragraph(_money(ln.get("rate")), s["body_right"]),
            Paragraph(_money(ln.get("amount")), s["body_right"]),
        ])

    line_table = Table(
        rows,
        colWidths=[
            page_w * 0.50,   # description
            page_w * 0.10,   # qty
            page_w * 0.08,   # unit
            page_w * 0.16,   # rate
            page_w * 0.16,   # amount
        ],
        repeatRows=1,
    )
    line_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, INK),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 4 * mm))

    # ----- Totals
    subtotal = float(invoice.get("subtotal", 0))
    vat_pct = float(invoice.get("vat_pct", 15))
    vat_amount = float(invoice.get("vat_amount", 0))
    retention_pct = float(invoice.get("retention_pct", 0) or 0)
    retention_amount = float(invoice.get("retention_amount", 0) or 0)
    total = float(invoice.get("total", 0))
    paid_total = float(invoice.get("paid_total", 0) or 0)
    balance = float(invoice.get("balance", total - paid_total) or 0)

    totals_rows = [
        ["Subtotal (excl. VAT)", _money(subtotal)],
        [f"VAT @ {vat_pct:g}%", _money(vat_amount)],
    ]
    if retention_amount:
        totals_rows.append([f"Less retention ({retention_pct:g}%)", f"({_money(retention_amount)})"])
    totals_rows.append(["TOTAL DUE", _money(total)])
    if paid_total:
        totals_rows.append([f"Paid to date", f"({_money(paid_total)})"])
        totals_rows.append(["BALANCE OUTSTANDING", _money(balance)])

    totals_table = Table(
        totals_rows,
        colWidths=[page_w * 0.65, page_w * 0.20],
        hAlign="RIGHT",
    )
    style_cmds = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    # Bold the TOTAL DUE row
    total_row_idx = 2 if not retention_amount else 3
    style_cmds.extend([
        ("FONT", (0, total_row_idx), (-1, total_row_idx), "Helvetica-Bold", 10),
        ("LINEABOVE", (0, total_row_idx), (-1, total_row_idx), 0.6, INK),
        ("LINEBELOW", (0, total_row_idx), (-1, total_row_idx), 0.6, INK),
    ])
    if paid_total:
        bal_idx = total_row_idx + 2
        style_cmds.extend([
            ("FONT", (0, bal_idx), (-1, bal_idx), "Helvetica-Bold", 10),
            ("LINEABOVE", (0, bal_idx), (-1, bal_idx), 0.4, INK),
        ])
    totals_table.setStyle(TableStyle(style_cmds))
    story.append(totals_table)
    story.append(Spacer(1, 6 * mm))

    # ----- Banking details + payment terms
    extras: list = []
    if company.get("payment_terms"):
        extras.append(Paragraph(f"<b>Payment terms:</b> {_esc(company['payment_terms'])}", s["body"]))
        extras.append(Spacer(1, 2 * mm))
    if company.get("banking_details"):
        extras.append(Paragraph("<b>Banking details:</b>", s["body_bold"]))
        for line in str(company["banking_details"]).split("\n"):
            if line.strip():
                extras.append(Paragraph(_esc(line), s["body"]))
        extras.append(Spacer(1, 2 * mm))
    if invoice.get("notes"):
        extras.append(Paragraph(f"<b>Notes:</b> {_esc(invoice['notes'])}", s["body"]))
        extras.append(Spacer(1, 2 * mm))

    # SARS-required compliance footer
    extras.append(Spacer(1, 2 * mm))
    extras.append(Paragraph(
        "This document is a Tax Invoice in terms of section 20(4) of the Value-Added Tax "
        "Act, 1991. E&OE.",
        s["small"],
    ))

    for el in extras:
        story.append(el)

    doc.build(story)
    return buf.getvalue()


def render_statement_pdf(statement: dict, company: dict) -> bytes:
    """Render a per-client account statement (running ledger).

    `statement` is the dict from invoices.client_statement().
    """
    s = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title=f"Statement — {statement['client']}",
    )
    page_w = A4[0] - 36 * mm

    story: list = []

    # ----- Top band
    company_block = []
    company_block.append(Paragraph(_esc(company.get("company_name") or "NDLOVU T PROJECTS (PTY) LTD"), s["body_bold"]))
    if company.get("company_address"):
        for line in str(company["company_address"]).split("\n"):
            if line.strip():
                company_block.append(Paragraph(_esc(line), s["body"]))
    if company.get("company_vat_reg"):
        company_block.append(Paragraph(f"VAT Reg: {_esc(company['company_vat_reg'])}", s["body"]))

    right_block = [Paragraph("STATEMENT", s["title"])]
    today = datetime.now().strftime("%Y-%m-%d")
    right_block.append(Paragraph(f"Issued: {today}", s["body"]))

    top_table = Table([[company_block, right_block]],
                      colWidths=[page_w * 0.55, page_w * 0.45])
    top_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(top_table)
    story.append(Spacer(1, 5 * mm))

    # ----- Account header
    acct_lines = [Paragraph("<b>Account:</b>", s["body_bold"]),
                  Paragraph(_esc(statement.get("client", "")), s["body_bold"])]
    if statement.get("from") or statement.get("to"):
        acct_lines.append(Paragraph(
            f"Period: {_esc(statement.get('from') or 'all-time')} → {_esc(statement.get('to') or today)}",
            s["body"]
        ))
    acct_table = Table([[acct_lines]], colWidths=[page_w])
    acct_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(acct_table)
    story.append(Spacer(1, 4 * mm))

    # ----- Ledger table
    rows = [[
        Paragraph("<b>Date</b>", s["body"]),
        Paragraph("<b>Reference</b>", s["body"]),
        Paragraph("<b>Description</b>", s["body"]),
        Paragraph("<b>Debit</b>", s["body_right"]),
        Paragraph("<b>Credit</b>", s["body_right"]),
        Paragraph("<b>Balance</b>", s["body_right"]),
    ]]
    if statement.get("opening_balance"):
        rows.append([
            Paragraph(_esc(statement.get("from") or ""), s["body"]),
            Paragraph("Opening balance", s["body_bold"]),
            Paragraph("", s["body"]),
            Paragraph("", s["body_right"]),
            Paragraph("", s["body_right"]),
            Paragraph(_money(statement["opening_balance"]), s["body_right"]),
        ])
    for e in statement.get("entries", []):
        rows.append([
            Paragraph(_esc(e["date"]), s["body"]),
            Paragraph(_esc(e["ref"]), s["body"]),
            Paragraph(_esc(e.get("notes") or e["type"].title()), s["body"]),
            Paragraph(_money(e["debit"]) if e["debit"] else "", s["body_right"]),
            Paragraph(_money(e["credit"]) if e["credit"] else "", s["body_right"]),
            Paragraph(_money(e["balance"]), s["body_right"]),
        ])
    # Closing
    rows.append([
        Paragraph(_esc(statement.get("to") or today), s["body"]),
        Paragraph("<b>Closing balance</b>", s["body_bold"]),
        Paragraph("", s["body"]),
        Paragraph(_money(statement.get("total_invoiced", 0)), s["body_right"]),
        Paragraph(_money(statement.get("total_paid", 0)), s["body_right"]),
        Paragraph(f"<b>{_money(statement.get('closing_balance', 0))}</b>", s["body_right"]),
    ])

    ledger = Table(rows, colWidths=[
        page_w * 0.12, page_w * 0.20, page_w * 0.30,
        page_w * 0.13, page_w * 0.13, page_w * 0.12,
    ], repeatRows=1)
    ledger.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(ledger)
    story.append(Spacer(1, 5 * mm))

    if company.get("banking_details"):
        story.append(Paragraph("<b>Please remit to:</b>", s["body_bold"]))
        for line in str(company["banking_details"]).split("\n"):
            if line.strip():
                story.append(Paragraph(_esc(line), s["body"]))
        story.append(Spacer(1, 2 * mm))

    story.append(Paragraph("E&OE.", s["small"]))

    doc.build(story)
    return buf.getvalue()
