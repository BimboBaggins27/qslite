"""PDF renderer — matches the ATESS quote layout precisely.

Plain B&W. Logo top-right (FULL `NDLOVU T PROJECTS (Pty) Ltd`).
Compact top block. Single bordered table with wide Description column.
Zones inline as bold text in the description column (P&G's-style),
not as full-width header rows. Total row with rule above and below.
No QUOTATION badge, no banking, no acceptance, no timestamp.
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

INK = colors.black
RULE = colors.black


def _esc(s: str) -> str:
    """Escape & < > so they don't break Paragraph's mini-HTML parser."""
    return _escape(str(s or ""), entities={'"': "&quot;", "'": "&apos;"})


def _zone_order(zones: list[str]) -> list[str]:
    pgs = [z for z in zones if z.lower() in ("p&g", "p&g's", "pgs", "p&gs")]
    others = [z for z in zones if z not in pgs]
    return sorted(others) + sorted(pgs)


def _styles():
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("Body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=10, textColor=INK, leading=11.5),
        "body_bold": ParagraphStyle("BodyB", parent=base["Normal"], fontName="Helvetica-Bold",
                                    fontSize=10, textColor=INK, leading=11.5),
        "body_right": ParagraphStyle("BodyR", parent=base["Normal"], fontName="Helvetica",
                                     fontSize=10, textColor=INK, alignment=2, leading=11.5),
        "body_center": ParagraphStyle("BodyC", parent=base["Normal"], fontName="Helvetica",
                                      fontSize=10, textColor=INK, alignment=1, leading=11.5),
        "table_header": ParagraphStyle("TH", parent=base["Normal"], fontName="Helvetica-Bold",
                                       fontSize=10, textColor=INK, leading=12),
        "centered_bold": ParagraphStyle("CenterBold", parent=base["Normal"], fontName="Helvetica-Bold",
                                        fontSize=11, textColor=INK, alignment=1, leading=13),
        "subject": ParagraphStyle("Subject", parent=base["Normal"], fontName="Helvetica-Bold",
                                  fontSize=11, textColor=INK, leading=14),
        "total_bold": ParagraphStyle("Total", parent=base["Normal"], fontName="Helvetica-Bold",
                                     fontSize=11, textColor=INK, leading=13),
        "total_right": ParagraphStyle("TotalR", parent=base["Normal"], fontName="Helvetica-Bold",
                                      fontSize=11, textColor=INK, alignment=2, leading=13),
    }


def _money(v: float) -> str:
    return f"{v:,.2f}"


def _logo_flowable(target_width_mm: float = 45.0):
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


def render_quote_pdf(quote: dict) -> bytes:
    header = quote.get("header") or {}
    items = quote.get("items", [])
    total = quote.get("total_zar", 0.0)
    show_vat = bool(header.get("show_vat"))
    vat_pct = float(header.get("vat_pct") or 15.0)

    ss = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title=f"Quote {header.get('quote_no', '')}".strip() or "Quotation",
        author=header.get("company_name", ""),
    )

    story = []

    # ---------- TOP BLOCK: client info left, logo right ----------
    client_lines = []
    if header.get("client_name"):
        client_lines.append(Paragraph(f"<b>{_esc(header['client_name'])}</b>", ss["body_bold"]))
    vat_text = "Vat Reg No:" + (f" {_esc(header['client_vat_reg'])}" if header.get("client_vat_reg") else "")
    client_lines.append(Paragraph(vat_text, ss["body"]))
    if header.get("client_address"):
        client_lines.append(Paragraph(f"<b>{_esc(header['client_address'])}</b>", ss["body_bold"]))

    logo = _logo_flowable(45.0)
    right_cell = [logo] if logo else [Paragraph("", ss["body"])]

    top = Table([[client_lines, right_cell]], colWidths=[110 * mm, 64 * mm])
    top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(top)
    story.append(Spacer(1, 8 * mm))

    # ---------- DATE LEFT, QUOTE NO CENTERED — ATESS-style tight row ----------
    date_qno = Table([[
        Paragraph(f"<b>{_esc(header.get('quote_date', ''))}</b>" if header.get("quote_date") else "", ss["body_bold"]),
        Paragraph(f"<b>Quote No: {_esc(header['quote_no'])}</b>" if header.get("quote_no") else "", ss["centered_bold"]),
    ]], colWidths=[55 * mm, 119 * mm])
    date_qno.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(date_qno)
    story.append(Spacer(1, 5 * mm))

    # ---------- ATTENTION ----------
    if header.get("attention"):
        att = Table(
            [[Paragraph("<b>ATTENTION:</b>", ss["body_bold"]),
              Paragraph(_esc(header["attention"]), ss["body"])]],
            colWidths=[28 * mm, 146 * mm],
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
        story.append(Paragraph(f'<u>RE: {_esc(header["re_subject"])}</u>', ss["subject"]))
        story.append(Spacer(1, 3 * mm))

    # ---------- TABLE: header + items ----------
    # ATESS proportions: Description ~62%, Unit/Qty/Rate/Amount narrow
    col_widths = [108 * mm, 12 * mm, 12 * mm, 20 * mm, 22 * mm]

    rows: list[list] = []
    style_ops: list = []

    # Header row
    rows.append([
        Paragraph("<b>DESCRIPTION</b>", ss["table_header"]),
        Paragraph("<b>UNIT</b>", ParagraphStyle("HU", parent=ss["table_header"], alignment=1)),
        Paragraph("<b>QTY</b>", ParagraphStyle("HQ", parent=ss["table_header"], alignment=1)),
        Paragraph("<b>RATE</b>", ParagraphStyle("HR", parent=ss["table_header"], alignment=1)),
        Paragraph("<b>AMOUNT</b>", ParagraphStyle("HA", parent=ss["table_header"], alignment=1)),
    ])

    # Group by zone — zones rendered as inline bold lines INSIDE the description column
    by_zone: dict[str, list[dict]] = OrderedDict()
    for li in items:
        z = li.get("zone") or "Default"
        by_zone.setdefault(z, []).append(li)
    ordered = _zone_order(list(by_zone.keys()))

    # If only "Default" zone exists, skip zone labels entirely (just like ATESS)
    show_zone_labels = not (len(by_zone) == 1 and "Default" in by_zone)

    row_idx = 1
    for zone in ordered:
        zlist = by_zone[zone]
        if not zlist:
            continue
        # Zone label as inline bold first row in the description column
        if show_zone_labels and zone != "Default":
            rows.append([
                Paragraph(f"<b>{_esc(zone)}</b>", ss["body_bold"]),
                Paragraph("", ss["body"]),
                Paragraph("", ss["body"]),
                Paragraph("", ss["body"]),
                Paragraph("", ss["body"]),
            ])
            row_idx += 1
        for li in zlist:
            qty = float(li.get("quantity", 0))
            rate = float(li.get("rate_zar", 0))
            amount = round(qty * rate, 2)
            rows.append([
                Paragraph(_esc(li.get("description") or ""), ss["body"]),
                Paragraph(_esc(li.get("unit") or ""), ss["body_center"]),
                Paragraph(_money(qty), ss["body_right"]),
                Paragraph(_money(rate), ss["body_right"]),
                Paragraph(_money(amount), ss["body_right"]),
            ])
            row_idx += 1

    # Table style: outer box + internal column lines, NO row dividers (matches ATESS)
    style_ops += [
        ("BOX", (0, 0), (-1, -1), 0.7, RULE),
        # vertical separators between columns
        ("LINEAFTER", (0, 0), (0, -1), 0.5, RULE),
        ("LINEAFTER", (1, 0), (1, -1), 0.5, RULE),
        ("LINEAFTER", (2, 0), (2, -1), 0.5, RULE),
        ("LINEAFTER", (3, 0), (3, -1), 0.5, RULE),
        # bottom rule under header row only
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, RULE),
        # tight padding
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        # header row has slightly more padding
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
    ]

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(style_ops))
    story.append(table)
    story.append(Spacer(1, 6 * mm))

    # ---------- TOTAL — full-width, rule above and below ----------
    total_label = "TOTAL QUOTATION EXCLUDING VAT" if not show_vat else "SUBTOTAL EXCLUDING VAT"
    total_tbl = Table(
        [[Paragraph(f"<b>{_esc(total_label)}</b>", ss["total_bold"]),
          Paragraph(f"<b>{_money(total)}</b>", ss["total_right"])]],
        colWidths=[152 * mm, 22 * mm],
    )
    total_tbl.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(total_tbl)

    if show_vat:
        vat_amount = round(total * vat_pct / 100.0, 2)
        vat_tbl = Table([
            [Paragraph(f"<b>VAT @ {vat_pct:g}%</b>", ss["total_bold"]),
             Paragraph(f"<b>{_money(vat_amount)}</b>", ss["total_right"])],
            [Paragraph("<b>TOTAL QUOTATION INCLUDING VAT</b>", ss["total_bold"]),
             Paragraph(f"<b>{_money(total + vat_amount)}</b>", ss["total_right"])],
        ], colWidths=[152 * mm, 22 * mm])
        vat_tbl.setStyle(TableStyle([
            ("LINEBELOW", (0, 1), (-1, 1), 0.7, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(vat_tbl)

    story.append(Spacer(1, 8 * mm))

    # ---------- PAYMENT TERMS ----------
    if header.get("payment_terms"):
        story.append(Paragraph("<b>Payment Terms</b>", ss["body_bold"]))
        for line in str(header["payment_terms"]).splitlines():
            line = line.strip()
            if line:
                story.append(Paragraph(f"<b>{_esc(line)}</b>", ss["body_bold"]))

    doc.build(story)
    return buf.getvalue()
