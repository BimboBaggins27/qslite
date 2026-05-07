"""Excel renderer — matches the ATESS quote layout exactly.

Plain B&W, flat single-table, zones as inline bold rows (option 3b).
No QUOTATION badge, no BILL TO label, no banking footer, no acceptance block,
no quote-ID timestamp. Logo in the top-right corner.
"""
from __future__ import annotations

import io
from collections import OrderedDict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter


LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"

# Plain styles — match ATESS
TITLE_FONT = Font(name="Calibri", bold=True, size=11)
BODY_FONT = Font(name="Calibri", size=10)
BODY_BOLD = Font(name="Calibri", bold=True, size=10)
TABLE_HEADER_FONT = Font(name="Calibri", bold=True, size=10)
SECTION_FONT = Font(name="Calibri", bold=True, size=10)  # for inline zone/P&G rows
TOTAL_FONT = Font(name="Calibri", bold=True, size=11)
SUBJECT_FONT = Font(name="Calibri", bold=True, size=11, underline="single")

THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TOP_RULE = Border(top=THIN)

LEFT = Alignment(horizontal="left", vertical="top", wrap_text=True)
LEFT_C = Alignment(horizontal="left", vertical="center", wrap_text=True)
CENTER = Alignment(horizontal="center", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")

NUM_FMT = "#,##0.00"


# Order zones / sections appear in. P&G's always last.
def _zone_order(zones: list[str]) -> list[str]:
    norm = {z: z for z in zones}
    pgs_keys = [z for z in zones if z.lower() in ("p&g", "p&g's", "pgs", "p&gs")]
    others = [z for z in zones if z not in pgs_keys]
    return sorted(others) + sorted(pgs_keys)


def _set(ws, row, col, value, *, font=None, alignment=None, border=None, number_format=None):
    c = ws.cell(row=row, column=col, value=value)
    if font: c.font = font
    if alignment: c.alignment = alignment
    if border: c.border = border
    if number_format: c.number_format = number_format
    return c


def issued_quote_to_xlsx(quote: dict) -> bytes:
    header = quote.get("header") or {}
    items = quote.get("items", [])
    total = quote["total_zar"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Quotation"

    # 5 columns: Description | Unit | Qty | Rate | Amount  (ATESS proportions)
    widths = [70, 7, 8, 12, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ---------- TOP BLOCK (client info left, logo right) ----------
    row = 1
    # Client block (left)
    _set(ws, row, 1, header.get("client_name") or "", font=BODY_BOLD, alignment=LEFT)
    row += 1
    vat_label = "Vat Reg No:" + (f" {header['client_vat_reg']}" if header.get("client_vat_reg") else "")
    _set(ws, row, 1, vat_label, font=BODY_FONT, alignment=LEFT)
    row += 1
    if header.get("client_address"):
        _set(ws, row, 1, header["client_address"], font=BODY_BOLD, alignment=LEFT)
        row += 1

    # Logo (right) — anchor in top-right area; sits across rows 1-4
    if LOGO_PATH.exists():
        try:
            img = XLImage(str(LOGO_PATH))
            # Scale to roughly 180px wide while keeping aspect
            ratio = 180 / img.width
            img.width = 180
            img.height = int(img.height * ratio)
            img.anchor = "D1"
            ws.add_image(img)
        except Exception:
            pass

    # Spacer (matches ATESS gap)
    row = max(row, 5) + 2

    # ---------- DATE + QUOTE NO ----------
    if header.get("quote_date"):
        _set(ws, row, 1, header["quote_date"], font=BODY_BOLD, alignment=LEFT)
    if header.get("quote_no"):
        c = _set(ws, row, 3, f"Quote No: {header['quote_no']}", font=BODY_BOLD, alignment=CENTER)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
    row += 2

    # ---------- ATTENTION ----------
    if header.get("attention"):
        _set(ws, row, 1, "ATTENTION:", font=BODY_BOLD, alignment=LEFT)
        _set(ws, row, 2, header["attention"], font=BODY_FONT, alignment=LEFT)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        row += 2

    # ---------- RE ----------
    if header.get("re_subject"):
        _set(ws, row, 1, f"RE: {header['re_subject']}", font=SUBJECT_FONT, alignment=LEFT)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 2

    # ---------- TABLE HEADER ----------
    headers_text = ["DESCRIPTION", "UNIT", "QTY", "RATE", "AMOUNT"]
    aligns = [LEFT_C, CENTER, CENTER, CENTER, CENTER]
    for col_idx, (h, a) in enumerate(zip(headers_text, aligns), start=1):
        _set(ws, row, col_idx, h, font=TABLE_HEADER_FONT, alignment=a, border=BOX)
    ws.row_dimensions[row].height = 20
    row += 1

    # ---------- ITEMS — flat table, zones as inline bold rows ----------
    zones: OrderedDict[str, list[dict]] = OrderedDict()
    for li in items:
        z = li.get("zone") or "Default"
        zones.setdefault(z, []).append(li)
    ordered_zones = _zone_order(list(zones.keys()))

    # Skip zone labels entirely if there's only the "Default" zone (matches ATESS — no labels at all)
    show_zone_labels = not (len(zones) == 1 and "Default" in zones)

    for zone in ordered_zones:
        zone_items = zones[zone]
        if not zone_items:
            continue
        # Inline bold zone header — skip "Default"
        if show_zone_labels and zone != "Default":
            _set(ws, row, 1, zone, font=SECTION_FONT, alignment=LEFT, border=BOX)
            for col in range(2, 6):
                _set(ws, row, col, "", border=BOX)
            row += 1

        for li in zone_items:
            qty = float(li.get("quantity", 0))
            rate = float(li.get("rate_zar", 0))
            amount = round(qty * rate, 2)
            _set(ws, row, 1, li.get("description") or "", font=BODY_FONT, alignment=LEFT_C, border=BOX)
            _set(ws, row, 2, li.get("unit") or "", font=BODY_FONT, alignment=CENTER, border=BOX)
            _set(ws, row, 3, qty, font=BODY_FONT, alignment=RIGHT, number_format=NUM_FMT, border=BOX)
            _set(ws, row, 4, rate, font=BODY_FONT, alignment=RIGHT, number_format=NUM_FMT, border=BOX)
            _set(ws, row, 5, amount, font=BODY_FONT, alignment=RIGHT, number_format=NUM_FMT, border=BOX)
            row += 1

    row += 1  # spacer

    # ---------- TOTAL ----------
    show_vat = bool(header.get("show_vat"))
    vat_pct = float(header.get("vat_pct") or 15.0)
    label = "TOTAL QUOTATION EXCLUDING VAT" if not show_vat else "SUBTOTAL EXCLUDING VAT"
    _set(ws, row, 1, label, font=TOTAL_FONT, alignment=LEFT, border=TOP_RULE)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    _set(ws, row, 5, total, font=TOTAL_FONT, alignment=RIGHT, number_format=NUM_FMT, border=TOP_RULE)
    row += 1

    if show_vat:
        vat_amount = round(total * vat_pct / 100.0, 2)
        _set(ws, row, 1, f"VAT @ {vat_pct:g}%", font=TOTAL_FONT, alignment=LEFT)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        _set(ws, row, 5, vat_amount, font=TOTAL_FONT, alignment=RIGHT, number_format=NUM_FMT)
        row += 1
        _set(ws, row, 1, "TOTAL QUOTATION INCLUDING VAT", font=TOTAL_FONT, alignment=LEFT, border=TOP_RULE)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        _set(ws, row, 5, round(total + vat_amount, 2), font=TOTAL_FONT, alignment=RIGHT, number_format=NUM_FMT, border=TOP_RULE)
        row += 1

    row += 2

    # ---------- PAYMENT TERMS (all bold, plain) ----------
    if header.get("payment_terms"):
        _set(ws, row, 1, "Payment Terms", font=BODY_BOLD, alignment=LEFT)
        row += 1
        for line in str(header["payment_terms"]).splitlines():
            line = line.strip()
            if not line:
                continue
            _set(ws, row, 1, line, font=BODY_BOLD, alignment=LEFT)
            row += 1

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
