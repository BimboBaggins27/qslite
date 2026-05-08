"""Invoicing + receivables — the Pastel-replacement core for SA construction.

Public surface:
  - next_invoice_no(prefix="INV")             -> str (auto-incrementing per year)
  - create_invoice(...)                       -> int (invoice_id)
  - convert_quote_to_invoice(quote_id, ...)   -> int
  - get_invoice(invoice_id)                   -> dict | None
  - list_invoices(client=None, status=None)   -> list[dict]
  - update_invoice_status(invoice_id, status) -> None
  - delete_invoice(invoice_id)                -> None
  - record_payment(invoice_id, amount, ...)   -> int (payment_id)
  - list_payments(invoice_id)                 -> list[dict]
  - delete_payment(payment_id)                -> None
  - invoice_balance(invoice_id)               -> float (outstanding)
  - aged_debtors(as_of=None)                  -> list[dict] per client
  - client_statement(client_name, from_date=None, to_date=None) -> dict

VAT defaults to 15% (SA standard rate). Retention defaults to 0 (set
explicitly per invoice when needed for progress claims).

All amounts are stored in ZAR. invoice_date / due_date are ISO YYYY-MM-DD.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from memory import _conn, transaction  # reuse the shared connection helpers


# ----- Number formatting helpers --------------------------------------------

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _to_iso(s: str) -> str:
    """Normalise a date string into ISO YYYY-MM-DD. Returns today on parse failure."""
    if not s:
        return _today()
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    return _today()


def _next_invoice_no_in_tx(con: sqlite3.Connection, prefix: str = "INV") -> str:
    """Compute the next invoice number using the supplied connection (which
    must already be inside a BEGIN IMMEDIATE). Caller is responsible for
    committing — the calling INSERT and this number generation must be in the
    same transaction so two simultaneous Convert-to-invoice clicks can't
    produce duplicate numbers."""
    year = datetime.now().strftime("%Y")
    pattern = f"{prefix}-{year}-%"
    rows = con.execute(
        "SELECT invoice_no FROM invoices WHERE invoice_no LIKE ?", (pattern,)
    ).fetchall()
    max_n = 0
    for r in rows:
        try:
            n = int(r["invoice_no"].rsplit("-", 1)[-1])
            max_n = max(max_n, n)
        except (ValueError, IndexError):
            continue
    return f"{prefix}-{year}-{max_n + 1:04d}"


def next_invoice_no(prefix: str = "INV") -> str:
    """Public read-only convenience — returns what the next invoice number
    *would* be if generated right now. Subject to races; for actual issue use
    `_next_invoice_no_in_tx` inside a transaction."""
    with transaction() as con:
        return _next_invoice_no_in_tx(con, prefix)


# ----- Core CRUD ------------------------------------------------------------

def create_invoice(
    client_name: str,
    project_name: Optional[str],
    lines: list[dict],
    *,
    invoice_no: Optional[str] = None,
    invoice_date: Optional[str] = None,
    due_days: int = 30,
    vat_pct: float = 15.0,
    retention_pct: float = 0.0,
    re_subject: Optional[str] = None,
    notes: Optional[str] = None,
    quote_id: Optional[str] = None,
    client_address: Optional[str] = None,
    client_vat_reg: Optional[str] = None,
    client_attention: Optional[str] = None,
    status: str = "draft",
) -> int:
    """Create a new invoice + lines. Returns the invoice id.

    `lines` is a list of dicts with keys: description, quantity, unit, rate
    (optional: trade). Amount is computed as quantity * rate.

    Subtotal is the sum of line amounts (ex VAT).
    VAT is computed on subtotal at vat_pct%.
    Retention is computed on subtotal at retention_pct% (held back).
    Total = subtotal + vat_amount - retention_amount.
    """
    if not client_name or not str(client_name).strip():
        raise ValueError("client_name is required")
    if not lines:
        raise ValueError("at least one line is required")

    inv_date = _to_iso(invoice_date) if invoice_date else _today()
    due = (
        (datetime.strptime(inv_date, "%Y-%m-%d") + timedelta(days=int(due_days)))
        .strftime("%Y-%m-%d")
    )

    # Compute amounts on each line and total
    subtotal = 0.0
    prepared_lines = []
    for ln in lines:
        qty = float(ln.get("quantity") or 0)
        rate = float(ln.get("rate") or 0)
        amount = round(qty * rate, 2)
        subtotal += amount
        prepared_lines.append({
            "description": str(ln.get("description") or ""),
            "quantity": qty,
            "unit": str(ln.get("unit") or "no"),
            "rate": rate,
            "amount": amount,
            "trade": ln.get("trade"),
        })

    subtotal = round(subtotal, 2)
    vat_amount = round(subtotal * float(vat_pct) / 100.0, 2)
    retention_amount = round(subtotal * float(retention_pct) / 100.0, 2)
    total = round(subtotal + vat_amount - retention_amount, 2)

    now = datetime.utcnow().isoformat()
    # Atomic: invoice number generation + insert + line inserts must be one transaction
    # so concurrent writers can't collide on the unique invoice_no.
    with transaction() as con:
        inv_no = invoice_no or _next_invoice_no_in_tx(con)
        cur = con.execute(
            """
            INSERT INTO invoices(
                invoice_no, client_name, client_address, client_vat_reg, client_attention,
                project_name, quote_id, invoice_date, due_date,
                subtotal, vat_pct, vat_amount, retention_pct, retention_amount, total,
                status, re_subject, notes, created_at
            ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?,?,?, ?,?,?,?)
            """,
            (
                inv_no, client_name.strip(),
                (client_address or None),
                (client_vat_reg or None),
                (client_attention or None),
                (project_name or None),
                (quote_id or None),
                inv_date, due,
                subtotal, vat_pct, vat_amount, retention_pct, retention_amount, total,
                status, (re_subject or None), (notes or None), now,
            ),
        )
        invoice_id = int(cur.lastrowid)
        for ln in prepared_lines:
            con.execute(
                "INSERT INTO invoice_lines(invoice_id, description, quantity, unit, rate, amount, trade) VALUES (?,?,?,?,?,?,?)",
                (invoice_id, ln["description"], ln["quantity"], ln["unit"], ln["rate"], ln["amount"], ln["trade"]),
            )
    return invoice_id


def convert_quote_to_invoice(
    quote_id: str,
    *,
    invoice_no: Optional[str] = None,
    invoice_date: Optional[str] = None,
    due_days: int = 30,
    vat_pct: float = 15.0,
    retention_pct: float = 0.0,
    status: str = "draft",
) -> int:
    """Materialise an issued quote into an invoice draft. Returns invoice_id.

    Pulls header + line items from the quote payload, applies VAT and (optionally)
    retention. The quote remains in `issued_quotes`; this just creates a linked
    invoice. Multiple invoices can reference the same quote (for progress claims).
    """
    with _conn() as con:
        row = con.execute(
            "SELECT payload FROM issued_quotes WHERE id = ?", (quote_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"quote_id {quote_id!r} not found")

    payload = json.loads(row["payload"])
    header = payload.get("header") or {}
    qitems = payload.get("items") or []

    lines = [
        {
            "description": it.get("description", ""),
            "quantity": it.get("quantity", 0),
            "unit": it.get("unit", "no"),
            "rate": it.get("rate_zar", 0),
            "trade": it.get("trade"),
        }
        for it in qitems
    ]

    return create_invoice(
        client_name=(header.get("client_name") or "").strip() or "Unknown",
        project_name=(header.get("project") or None),
        lines=lines,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        due_days=due_days,
        vat_pct=vat_pct,
        retention_pct=retention_pct,
        re_subject=(header.get("re_subject") or header.get("quote_name")),
        quote_id=quote_id,
        client_address=(header.get("client_address") or None),
        client_vat_reg=(header.get("client_vat_reg") or None),
        client_attention=(header.get("attention") or None),
        status=status,
    )


def get_invoice(invoice_id: int) -> Optional[dict]:
    """Return invoice header + lines + payments as a single dict, or None."""
    with _conn() as con:
        inv = con.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not inv:
            return None
        lines = con.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY id",
            (invoice_id,),
        ).fetchall()
        pays = con.execute(
            "SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date, id",
            (invoice_id,),
        ).fetchall()
    out = dict(inv)
    out["lines"] = [dict(r) for r in lines]
    out["payments"] = [dict(r) for r in pays]
    out["paid_total"] = round(sum(p["amount"] for p in out["payments"]), 2)
    out["balance"] = round(out["total"] - out["paid_total"], 2)
    return out


def list_invoices(
    client_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    """List invoices with optional filters. Includes paid_total + balance per row."""
    where: list[str] = []
    params: list = []
    if client_name:
        where.append("client_name = ?")
        params.append(client_name)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM invoices"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY invoice_date DESC, id DESC LIMIT ?"
    params.append(int(limit))

    with _conn() as con:
        rows = con.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            paid = con.execute(
                "SELECT COALESCE(SUM(amount), 0) AS p FROM payments WHERE invoice_id = ?",
                (d["id"],),
            ).fetchone()
            d["paid_total"] = round(paid["p"] or 0, 2)
            d["balance"] = round(d["total"] - d["paid_total"], 2)
            out.append(d)
    return out


def update_invoice_status(invoice_id: int, status: str) -> None:
    if status not in ("draft", "issued", "partial", "paid", "void"):
        raise ValueError(f"unknown status: {status!r}")
    with _conn() as con:
        con.execute("UPDATE invoices SET status = ? WHERE id = ?", (status, invoice_id))


def delete_invoice(invoice_id: int) -> None:
    # FK constraints with ON DELETE CASCADE will handle children; explicit
    # deletes are kept as defence-in-depth for older databases that may
    # have been created before WAL+FK enforcement was on.
    with transaction() as con:
        con.execute("DELETE FROM payments WHERE invoice_id = ?", (invoice_id,))
        con.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
        con.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


# ----- Payments -------------------------------------------------------------

def record_payment(
    invoice_id: int,
    amount: float,
    *,
    payment_date: Optional[str] = None,
    method: Optional[str] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    """Record a payment against an invoice. Auto-updates invoice status:
    balance == 0 → 'paid'; balance > 0 and any payment exists → 'partial'."""
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("payment amount must be positive")
    pdate = _to_iso(payment_date) if payment_date else _today()
    now = datetime.utcnow().isoformat()
    # Atomic: payment insert + status recompute must be a single transaction
    # so a concurrent reader never sees a payment with stale invoice status.
    with transaction() as con:
        cur = con.execute(
            "INSERT INTO payments(invoice_id, payment_date, amount, method, reference, notes, created_at) VALUES (?,?,?,?,?,?,?)",
            (invoice_id, pdate, amount, method, reference, notes, now),
        )
        payment_id = int(cur.lastrowid)
        inv = con.execute("SELECT total FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if inv:
            paid = con.execute(
                "SELECT COALESCE(SUM(amount), 0) AS p FROM payments WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
            paid_total = round(paid["p"] or 0, 2)
            balance = round(inv["total"] - paid_total, 2)
            if balance <= 0.005:
                new_status = "paid"
            elif paid_total > 0:
                new_status = "partial"
            else:
                new_status = "issued"
            con.execute("UPDATE invoices SET status = ? WHERE id = ?", (new_status, invoice_id))
    return payment_id


def list_payments(invoice_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date, id",
            (invoice_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_payment(payment_id: int) -> None:
    with transaction() as con:
        row = con.execute("SELECT invoice_id FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if not row:
            return
        invoice_id = row["invoice_id"]
        con.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
        inv = con.execute("SELECT total FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if inv:
            paid = con.execute(
                "SELECT COALESCE(SUM(amount), 0) AS p FROM payments WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
            paid_total = round(paid["p"] or 0, 2)
            balance = round(inv["total"] - paid_total, 2)
            if balance <= 0.005:
                new_status = "paid"
            elif paid_total > 0:
                new_status = "partial"
            else:
                new_status = "issued"
            con.execute("UPDATE invoices SET status = ? WHERE id = ?", (new_status, invoice_id))


def invoice_balance(invoice_id: int) -> float:
    inv = get_invoice(invoice_id)
    return inv["balance"] if inv else 0.0


# ----- Receivables reports --------------------------------------------------

def aged_debtors(as_of: Optional[str] = None) -> list[dict]:
    """Aged-debtor summary per client, bucketed by days overdue.

    Buckets: current (not yet due), 1-30, 31-60, 61-90, 90+.
    Returns list[{client, current, b30, b60, b90, b90plus, total}], sorted by total desc.
    """
    asof_date = datetime.strptime(_to_iso(as_of) if as_of else _today(), "%Y-%m-%d")

    with _conn() as con:
        rows = con.execute(
            """
            SELECT i.client_name, i.id, i.due_date, i.total,
                   COALESCE((SELECT SUM(amount) FROM payments p WHERE p.invoice_id = i.id), 0) AS paid
            FROM invoices i
            WHERE i.status IN ('issued', 'partial')
            """
        ).fetchall()

    buckets: dict[str, dict] = {}
    for r in rows:
        bal = round(float(r["total"]) - float(r["paid"]), 2)
        if bal <= 0.005:
            continue
        client = r["client_name"]
        b = buckets.setdefault(client, {
            "client": client, "current": 0.0,
            "b30": 0.0, "b60": 0.0, "b90": 0.0, "b90plus": 0.0, "total": 0.0,
        })
        try:
            due = datetime.strptime(r["due_date"], "%Y-%m-%d")
            days_overdue = (asof_date - due).days
        except (ValueError, TypeError):
            days_overdue = 0
        if days_overdue <= 0:
            b["current"] += bal
        elif days_overdue <= 30:
            b["b30"] += bal
        elif days_overdue <= 60:
            b["b60"] += bal
        elif days_overdue <= 90:
            b["b90"] += bal
        else:
            b["b90plus"] += bal
        b["total"] += bal

    out = list(buckets.values())
    for b in out:
        for k in ("current", "b30", "b60", "b90", "b90plus", "total"):
            b[k] = round(b[k], 2)
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


def client_statement(
    client_name: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> dict:
    """Return a per-client ledger of invoices and payments in date order.

    Output:
        {
          "client": str,
          "from": YYYY-MM-DD or None,
          "to": YYYY-MM-DD or None,
          "entries": [{date, type, ref, debit, credit, balance, notes}],
          "opening_balance": float,
          "closing_balance": float,
          "total_invoiced": float,
          "total_paid": float,
        }
    """
    with _conn() as con:
        invs = con.execute(
            "SELECT id, invoice_no, invoice_date, total, status, re_subject FROM invoices WHERE client_name = ? ORDER BY invoice_date, id",
            (client_name,),
        ).fetchall()
        pays = con.execute(
            """
            SELECT p.id, p.payment_date, p.amount, p.method, p.reference, p.notes,
                   i.invoice_no
            FROM payments p
            JOIN invoices i ON i.id = p.invoice_id
            WHERE i.client_name = ?
            ORDER BY p.payment_date, p.id
            """,
            (client_name,),
        ).fetchall()

    events = []
    for r in invs:
        if r["status"] == "void":
            continue
        events.append({
            "date": r["invoice_date"],
            "type": "invoice",
            "ref": r["invoice_no"],
            "debit": round(float(r["total"]), 2),
            "credit": 0.0,
            "notes": r["re_subject"] or "",
        })
    for r in pays:
        events.append({
            "date": r["payment_date"],
            "type": "payment",
            "ref": f"{r['invoice_no']} — {r['method'] or 'payment'}{(' (' + r['reference'] + ')') if r['reference'] else ''}",
            "debit": 0.0,
            "credit": round(float(r["amount"]), 2),
            "notes": r["notes"] or "",
        })
    events.sort(key=lambda e: (e["date"], 0 if e["type"] == "invoice" else 1))

    # Filter window + running balance
    fd = _to_iso(from_date) if from_date else None
    td = _to_iso(to_date) if to_date else None

    opening = 0.0
    if fd:
        for e in events:
            if e["date"] < fd:
                opening += e["debit"] - e["credit"]
    opening = round(opening, 2)

    running = opening
    out_entries = []
    for e in events:
        if fd and e["date"] < fd:
            continue
        if td and e["date"] > td:
            continue
        running += e["debit"] - e["credit"]
        running = round(running, 2)
        e2 = dict(e)
        e2["balance"] = running
        out_entries.append(e2)

    total_invoiced = round(sum(e["debit"] for e in out_entries), 2)
    total_paid = round(sum(e["credit"] for e in out_entries), 2)

    return {
        "client": client_name,
        "from": fd, "to": td,
        "opening_balance": opening,
        "closing_balance": running,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "entries": out_entries,
    }
