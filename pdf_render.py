"""PDF renderer — pixel-faithful reproduction of NPQ 7624 (the reference quote).

Layout, top to bottom:
  1. Top band — logo LEFT, vendor info RIGHT (NDLOVU T PROJECTS bold,
     address, phones, emails, Reg No, VAT Reg No), thin rule beneath
  2. Client block (left-aligned, bold name + address + Reg / VAT)
  3. Date (left)
  4. Quote No: (centered, bold)
  5. ATTENTION: <name>
  6. RE: <subject> (bold + underlined)
  7. Items table — DESCRIPTION | UNIT | QTY | RATE | AMOUNT
     Zone headings rendered inline as bold rows
  8. Totals — TOTAL EX VAT / ADD 15% VAT / TOTAL INC VAT (banded grey)
  9. Payment Terms
 10. Thank-you paragraph
 11. Conditions list (italic, lettered a-i)
 12. Acceptance / sign block (Date / Quote No / Sign / ID No)
 13. Banking Details
 14. Plascon preferred applicator footer (if year set)

Money is rendered in SA convention: space thousands, comma decimal — e.g.
22 755,00. The `_money_sa` helper handles this.
"""
from __future__ import annotations

import io
from collections import OrderedDict
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
PLASCON_PATH = Path(__file__).parent / "assets" / "plascon-applicator.png"

INK = colors.black
RULE = colors.black
BAND = colors.Color(0.92, 0.92, 0.92)  # subtle grey for total bands


def _esc(s) -> str:
    return _escape(str(s or ""), entities={'"': "&quot;", "'": "&apos;"})


def _money_sa(v: float) -> str:
    """SA format: 22755 → '22 755,00' (space thousands, comma decimal)."""
    try:
        s = f"{float(v):,.2f}"
        # 22,755.00 → temp X swap → 22 755,00
        return s.replace(",", "X").replace(".", ",").replace("X", " ")
    except (TypeError, ValueError):
        return "0,00"


def _zone_order(zones: list[str]) -> list[str]:
    pgs = [z for z in zones if z.lower() in ("p&g", "p&g's", "pgs", "p&gs", "site")]
    others = [z for z in zones if z not in pgs]
    return sorted(others) + sorted(pgs)


def _styles():
    base = getSampleStyleSheet()
    return {
        "body":         ParagraphStyle("Body",  parent=base["Normal"], fontName="Helvetica",
                                       fontSize=10, textColor=INK, leading=12),
        "body_bold":    ParagraphStyle("BodyB", parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=10, textColor=INK, leading=12),
        "body_right":   ParagraphStyle("BodyR", parent=base["Normal"], fontName="Helvetica",
                                       fontSize=10, textColor=INK, alignment=2, leading=12),
        "body_center":  ParagraphStyle("BodyC", parent=base["Normal"], fontName="Helvetica",
                                       fontSize=10, textColor=INK, alignment=1, leading=12),
        "vendor_name":  ParagraphStyle("VName", parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=12, textColor=INK, alignment=1, leading=14),
        "vendor_meta":  ParagraphStyle("VMeta", parent=base["Normal"], fontName="Helvetica",
                                       fontSize=9, textColor=INK, alignment=1, leading=11),
        "table_header": ParagraphStyle("TH",    parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=10, textColor=INK, leading=12),
        "centered_bold":ParagraphStyle("CB",    parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=11, textColor=INK, alignment=1, leading=13),
        "subject":      ParagraphStyle("Sub",   parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=11, textColor=INK, leading=14),
        "total_bold":   ParagraphStyle("TB",    parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=10, textColor=INK, leading=12),
        "total_right":  ParagraphStyle("TR",    parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=10, textColor=INK, alignment=2, leading=12),
        "italic_small": ParagraphStyle("IS",    parent=base["Normal"], fontName="Helvetica-Oblique",
                                       fontSize=9, textColor=INK, leading=11.5),
        "italic_bold_small": ParagraphStyle("IBS", parent=base["Normal"], fontName="Helvetica-BoldOblique",
                                            fontSize=10, textColor=INK, leading=12),
    }


def _logo_flowable(target_width_mm: float = 38.0):
    if not LOGO_PATH.exists():
        return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(LOGO_PATH) as im:
            w, h = im.size
        target_w = target_width_mm * mm
        target_h = target_w * (h / w)
        return Image(str(LOGO_PATH), width=target_w, height=target_h)
    except Exception:
        return None


def _vendor_block(company: dict, ss) -> list:
    """Right-side header block — name / address / phones / emails / reg / VAT."""
    lines: list = [Paragraph(_esc(company.get("company_name") or "NDLOVU T PROJECTS (PTY) LTD"),
                             ss["vendor_name"])]
    if company.get("company_address"):
        lines.append(Paragraph(_esc(company["company_address"]), ss["vendor_meta"]))
    phones: list[str] = []
    if company.get("company_phone_robert"):
        phones.append(_esc(company["company_phone_robert"]))
    if company.get("company_phone_tina"):
        phones.append(_esc(company["company_phone_tina"]))
    if phones:
        lines.append(Paragraph("Tel: " + " | ".join(phones), ss["vendor_meta"]))
    elif company.get("company_contact"):
        lines.append(Paragraph("Tel: " + _esc(company["company_contact"]), ss["vendor_meta"]))
    emails: list[str] = []
    if company.get("company_email_robert"):
        emails.append(_esc(company["company_email_robert"]))
    if company.get("company_email_tina"):
        emails.append(_esc(company["company_email_tina"]))
    if emails:
        lines.append(Paragraph("Email: " + " | ".join(emails), ss["vendor_meta"]))
    if company.get("company_reg"):
        lines.append(Paragraph(f"Reg. No: {_esc(company['company_reg'])}", ss["vendor_meta"]))
    if company.get("company_vat_reg"):
        lines.append(Paragraph(f"VAT Reg. No: {_esc(company['company_vat_reg'])}", ss["vendor_meta"]))
    return lines


def render_quote_pdf(quote: dict) -> bytes:
    """Render the quote as bytes. `quote` is the dict from quote.freeze_quote()."""
    from company_profile import load_profile

    header = quote.get("header") or {}
    items = quote.get("items", [])
    total_ex = quote.get("total_zar", 0.0)
    show_vat = bool(header.get("show_vat", True))
    vat_pct = float(header.get("vat_pct") or 15.0)

    company = load_profile()
    for k, v in company.items():
        header.setdefault(k, v)

    ss = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title=f"Quote {header.get('quote_no', '')}".strip() or "Quotation",
        author=company.get("company_name", ""),
    )
    page_w = A4[0] - 36 * mm

    story: list = []

    # ---------- TOP BAND: logo LEFT, vendor info RIGHT ----------
    logo = _logo_flowable(38.0)
    left_cell = [logo] if logo else [Paragraph("", ss["body"])]
    right_cell = _vendor_block(company, ss)

    top_band = Table([[left_cell, right_cell]], colWidths=[page_w * 0.34, page_w * 0.66])
    top_band.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",  (0, 0), (0, 0), "LEFT"),
        ("ALIGN",  (1, 0), (1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(top_band)
    story.append(Spacer(1, 3 * mm))

    rule_tbl = Table([[""]], colWidths=[page_w])
    rule_tbl.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(rule_tbl)
    story.append(Spacer(1, 6 * mm))

    # ---------- CLIENT BLOCK ----------
    if header.get("client_name"):
        story.append(Paragraph(f"<b>{_esc(header['client_name'])}</b>", ss["body_bold"]))
    if header.get("client_address"):
        for line in str(header["client_address"]).split("\n"):
            line = line.strip()
            if line:
                story.append(Paragraph(f"<b>{_esc(line)}</b>", ss["body_bold"]))
    if header.get("client_reg"):
        story.append(Paragraph(f"<b>Reg:</b> {_esc(header['client_reg'])}", ss["body_bold"]))
    if header.get("client_vat_reg"):
        story.append(Paragraph(f"<b>VAT:</b> {_esc(header['client_vat_reg'])}", ss["body_bold"]))
    story.append(Spacer(1, 5 * mm))

    # ---------- DATE (left) ----------
    if header.get("quote_date"):
        story.append(Paragraph(f"<b>{_esc(header['quote_date'])}</b>", ss["body_bold"]))
        story.append(Spacer(1, 4 * mm))

    # ---------- QUOTE NO (centered) ----------
    if header.get("quote_no"):
        story.append(Paragraph(f"<b>Quote No: {_esc(header['quote_no'])}</b>", ss["centered_bold"]))
        story.append(Spacer(1, 4 * mm))

    # ---------- ATTENTION ----------
    if header.get("attention"):
        att = Table(
            [[Paragraph("<b>ATTENTION:</b>", ss["body_bold"]),
              Paragraph(f"<b>{_esc(header['attention'])}</b>", ss["body_bold"])]],
            colWidths=[28 * mm, page_w - 28 * mm],
        )
        att.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(att)
        story.append(Spacer(1, 4 * mm))

    # ---------- RE ----------
    if header.get("re_subject"):
        story.append(Paragraph(f'<b><u>RE: {_esc(header["re_subject"])}</u></b>', ss["subject"]))
        story.append(Spacer(1, 4 * mm))

    # ---------- LINE ITEMS TABLE ----------
    col_widths = [page_w * 0.50, page_w * 0.08, page_w * 0.08, page_w * 0.16, page_w * 0.18]

    rows: list[list] = [[
        Paragraph("<b>DESCRIPTION</b>", ss["table_header"]),
        Paragraph("<b>UNIT</b>",        ParagraphStyle("HU", parent=ss["table_header"], alignment=1)),
        Paragraph("<b>QTY</b>",         ParagraphStyle("HQ", parent=ss["table_header"], alignment=1)),
        Paragraph("<b>RATE</b>",        ParagraphStyle("HR", parent=ss["table_header"], alignment=2)),
        Paragraph("<b>AMOUNT</b>",      ParagraphStyle("HA", parent=ss["table_header"], alignment=2)),
    ]]
    style_ops: list = []

    by_zone: "OrderedDict[str, list[dict]]" = OrderedDict()
    for li in items:
        z = (li.get("zone") or "Default").strip() or "Default"
        by_zone.setdefault(z, []).append(li)
    ordered = _zone_order(list(by_zone.keys()))
    show_zone_labels = not (len(by_zone) == 1 and "Default" in by_zone)

    for zone in ordered:
        zlist = by_zone[zone]
        if not zlist:
            continue
        if show_zone_labels and zone != "Default":
            rows.append([
                Paragraph(f"<b>{_esc(zone)}</b>", ss["body_bold"]),
                "", "", "", "",
            ])
        for li in zlist:
            qty = float(li.get("quantity", 0))
            rate = float(li.get("rate_zar", 0))
            amount = round(qty * rate, 2)
            qty_str = f"{int(qty)}" if qty == int(qty) else _money_sa(qty)
            rows.append([
                Paragraph(_esc(li.get("description") or ""), ss["body"]),
                Paragraph(_esc(li.get("unit") or ""), ss["body_center"]),
                Paragraph(qty_str, ss["body_center"]),
                Paragraph(_money_sa(rate), ss["body_right"]),
                Paragraph(_money_sa(amount), ss["body_right"]),
            ])

    style_ops += [
        ("BOX", (0, 0), (-1, -1), 0.7, RULE),
        ("LINEAFTER", (0, 0), (0, -1), 0.5, RULE),
        ("LINEAFTER", (1, 0), (1, -1), 0.5, RULE),
        ("LINEAFTER", (2, 0), (2, -1), 0.5, RULE),
        ("LINEAFTER", (3, 0), (3, -1), 0.5, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
    ]

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(style_ops))
    story.append(table)
    story.append(Spacer(1, 1 * mm))

    # ---------- TOTALS ----------
    vat_amount = round(total_ex * vat_pct / 100.0, 2)
    total_inc = round(total_ex + vat_amount, 2)

    if show_vat:
        totals_rows = [
            [Paragraph("<b>TOTAL QUOTATION EXCLUDING VAT</b>", ss["total_bold"]),
             Paragraph(f"<b>{_money_sa(total_ex)}</b>",         ss["total_right"])],
            [Paragraph(f"<b>ADD {vat_pct:g}% VAT</b>",          ss["total_bold"]),
             Paragraph(f"<b>{_money_sa(vat_amount)}</b>",       ss["total_right"])],
            [Paragraph("<b>TOTAL QUOTATION INCLUDING VAT</b>",  ss["total_bold"]),
             Paragraph(f"<b>{_money_sa(total_inc)}</b>",        ss["total_right"])],
        ]
    else:
        totals_rows = [
            [Paragraph("<b>TOTAL QUOTATION</b>",                ss["total_bold"]),
             Paragraph(f"<b>{_money_sa(total_ex)}</b>",         ss["total_right"])],
        ]

    totals_tbl = Table(totals_rows, colWidths=[page_w * 0.78, page_w * 0.22])
    totals_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("BOX", (0, 0), (-1, -1), 0.7, RULE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 6 * mm))

    # ---------- PAYMENT TERMS ----------
    if header.get("payment_terms"):
        story.append(Paragraph("<b>Payment Terms:</b>", ss["body_bold"]))
        for line in str(header["payment_terms"]).splitlines():
            line = line.strip()
            if line:
                story.append(Paragraph(f"<b>{_esc(line)}</b>", ss["body_bold"]))
        story.append(Spacer(1, 4 * mm))

    # ---------- THANK-YOU PARAGRAPH ----------
    if company.get("thank_you_paragraph"):
        story.append(Paragraph(f"<b>{_esc(company['thank_you_paragraph'])}</b>", ss["body_bold"]))
        story.append(Spacer(1, 4 * mm))

    # ---------- CONDITIONS LIST ----------
    conditions = company.get("conditions") or []
    if conditions:
        story.append(Paragraph(
            "<b><i>Our quotation is subject to your acceptance of the following conditions: -</i></b>",
            ss["italic_bold_small"],
        ))
        labels = ["a", "b", "c", "d", "e", "f", "g", "h", "I", "j", "k"]
        for i, c in enumerate(conditions):
            label = labels[i] if i < len(labels) else f"{i+1}"
            story.append(Paragraph(f"<i>{label}) {_esc(c)}</i>", ss["italic_small"]))
        story.append(Spacer(1, 4 * mm))

    # ---------- ACCEPTANCE / SIGN BLOCK ----------
    if company.get("acceptance_block"):
        story.append(Paragraph(f"<b><i>{_esc(company['acceptance_block'])}</i></b>", ss["italic_bold_small"]))
        story.append(Spacer(1, 4 * mm))
        for label in ("Date:", "Quote No:", "Sign:", "ID No:"):
            story.append(Paragraph(f"<i>{label} ____________________</i>", ss["italic_small"]))
            story.append(Spacer(1, 2 * mm))
        story.append(Spacer(1, 2 * mm))

    # ---------- BANKING DETAILS ----------
    if company.get("banking_details"):
        story.append(Paragraph("<b>BANKING DETAILS:</b>", ss["body_bold"]))
        for line in str(company["banking_details"]).split("\n"):
            line = line.strip()
            if line:
                story.append(Paragraph(f"<b>{_esc(line)}</b>", ss["body_bold"]))
        story.append(Spacer(1, 4 * mm))

    # ---------- PLASCON FOOTER ----------
    plascon_year = company.get("plascon_applicator_year")
    if plascon_year:
        if PLASCON_PATH.exists():
            try:
                from PIL import Image as PILImage
                with PILImage.open(PLASCON_PATH) as im:
                    w, h = im.size
                tw = 60 * mm
                th = tw * (h / w)
                story.append(Image(str(PLASCON_PATH), width=tw, height=th))
            except Exception:
                story.append(Paragraph(
                    f"<b>Plascon preferred applicator {_esc(plascon_year)}</b>",
                    ss["body_bold"],
                ))
        else:
            # No image asset — render the textual fallback so the footer always appears
            story.append(Paragraph(
                f"<b>Plascon preferred applicator {_esc(plascon_year)}</b>",
                ss["body_bold"],
            ))

    doc.build(story)
    return buf.getvalue()
