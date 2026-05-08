"""POPIA (Protection of Personal Information Act) helpers for QSLite.

Not legal advice. This module gives you the operational hooks needed to
defend a complaint to the Information Regulator: data inventory, retention
enforcement, data-subject-access export, and breach-notification template.

Public surface:
    - data_inventory()         → dict listing tables and the personal info each holds
    - subject_access_export(client_name) → JSON dict of everything you hold on a client
    - subject_erasure(client_name, dry_run=True) → list rows that *would* be deleted
    - apply_retention(now=None, dry_run=True) → enforce 5-year SARS / X-year POPIA retention
    - breach_log(event, details) → append to data/popia_breach.log

Retention default: 5 years for invoice/payment/quote records (SARS s.55 of TAA).
Configurable via env: POPIA_RETENTION_YEARS (default 5).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from memory import _conn, transaction


_BREACH_LOG = Path(__file__).parent / "data" / "popia_breach.log"


def _retention_years() -> int:
    try:
        return int(os.environ.get("POPIA_RETENTION_YEARS", "5"))
    except ValueError:
        return 5


def data_inventory() -> dict:
    """Return a structured description of personal data stored in the DB.
    Use this to satisfy POPIA s.17 (record of processing activities)."""
    return {
        "controller": os.environ.get("POPIA_CONTROLLER", "Ndlovu T Projects (Pty) Ltd"),
        "information_officer": os.environ.get("POPIA_INFO_OFFICER", "(set POPIA_INFO_OFFICER in .env)"),
        "tables": {
            "clients": {
                "personal_info": ["name", "vat_reg", "address", "attention", "contact"],
                "lawful_basis": "contract performance",
                "retention_years": _retention_years(),
            },
            "issued_quotes": {
                "personal_info": ["client_name", "re_subject", "labels", "payload (full quote)"],
                "lawful_basis": "contract performance + SARS record-keeping",
                "retention_years": _retention_years(),
            },
            "invoices": {
                "personal_info": ["client_name", "client_address", "client_vat_reg",
                                  "client_attention", "amounts"],
                "lawful_basis": "contract performance + SARS s.55 (Tax Administration Act)",
                "retention_years": _retention_years(),
            },
            "payments": {
                "personal_info": ["amount", "method", "reference"],
                "lawful_basis": "contract performance + SARS",
                "retention_years": _retention_years(),
            },
            "projects_admin": {
                "personal_info": ["primary_client", "notes"],
                "lawful_basis": "contract performance",
                "retention_years": _retention_years(),
            },
            "rate_edits / qty_edits": {
                "personal_info": "none directly (operator edits to model behaviour)",
                "lawful_basis": "operational improvement (not personal info)",
                "retention_years": _retention_years(),
            },
        },
        "subject_rights": [
            "Right of access — `subject_access_export(client_name)`",
            "Right to correction — edit via Clients & Projects tab",
            "Right to deletion — `subject_erasure(client_name)`, subject to retention obligations",
            "Right to object — withhold data outside contract necessity",
        ],
    }


def subject_access_export(client_name: str) -> dict:
    """Return everything QSLite holds on a named client. Hand this to the
    data subject (the client) on written request — POPIA s.23."""
    out: dict = {"client_name": client_name, "exported_at": datetime.utcnow().isoformat()}
    with _conn() as con:
        client_row = con.execute(
            "SELECT * FROM clients WHERE name = ?", (client_name,)
        ).fetchone()
        out["client_record"] = dict(client_row) if client_row else None

        out["projects"] = [
            dict(r) for r in con.execute(
                "SELECT * FROM projects_admin WHERE primary_client = ?", (client_name,)
            ).fetchall()
        ]
        out["quotes"] = [
            dict(r) for r in con.execute(
                "SELECT id, issued_at, total_zar, project, quote_name, re_subject, quote_no FROM issued_quotes WHERE client_name = ?",
                (client_name,),
            ).fetchall()
        ]
        out["invoices"] = [
            dict(r) for r in con.execute(
                "SELECT * FROM invoices WHERE client_name = ?", (client_name,)
            ).fetchall()
        ]
        if out["invoices"]:
            inv_ids = tuple(i["id"] for i in out["invoices"])
            placeholders = ",".join("?" * len(inv_ids))
            out["invoice_lines"] = [
                dict(r) for r in con.execute(
                    f"SELECT * FROM invoice_lines WHERE invoice_id IN ({placeholders})",
                    inv_ids,
                ).fetchall()
            ]
            out["payments"] = [
                dict(r) for r in con.execute(
                    f"SELECT * FROM payments WHERE invoice_id IN ({placeholders})",
                    inv_ids,
                ).fetchall()
            ]
        else:
            out["invoice_lines"] = []
            out["payments"] = []
    return out


def subject_erasure(client_name: str, dry_run: bool = True) -> dict:
    """Erase a client's records *if and only if* retention has expired and no
    open balance exists. POPIA right-to-deletion is conditional on retention
    obligations — SARS demands 5-year retention so we cannot delete records
    younger than that.

    Returns a report of what would be deleted (dry_run=True) or was deleted.
    """
    cutoff = (datetime.now() - timedelta(days=_retention_years() * 365)).isoformat()
    report: dict = {
        "client_name": client_name,
        "dry_run": dry_run,
        "cutoff_date": cutoff,
        "deleted": {},
        "preserved": [],
    }
    with transaction() as con:
        # Open invoices block deletion
        open_inv = con.execute(
            "SELECT COUNT(*) c FROM invoices WHERE client_name = ? AND status NOT IN ('paid', 'void')",
            (client_name,),
        ).fetchone()
        if open_inv["c"] > 0:
            report["preserved"].append(f"{open_inv['c']} open invoice(s) — settle first")
            return report

        # Old paid invoices (and their children via FK cascade) past retention
        candidates = con.execute(
            "SELECT id FROM invoices WHERE client_name = ? AND created_at < ? AND status IN ('paid', 'void')",
            (client_name, cutoff),
        ).fetchall()
        report["deleted"]["invoices"] = len(candidates)

        old_quotes = con.execute(
            "SELECT id FROM issued_quotes WHERE client_name = ? AND issued_at < ?",
            (client_name, cutoff),
        ).fetchall()
        report["deleted"]["quotes"] = len(old_quotes)

        if not dry_run:
            for r in candidates:
                con.execute("DELETE FROM invoices WHERE id = ?", (r["id"],))
            for r in old_quotes:
                con.execute("DELETE FROM issued_quote_items WHERE quote_id = ?", (r["id"],))
                con.execute("DELETE FROM issued_quotes WHERE id = ?", (r["id"],))
    return report


def apply_retention(now: Optional[datetime] = None, dry_run: bool = True) -> dict:
    """Enforce blanket retention across all tables. Run nightly after backup."""
    now = now or datetime.now()
    cutoff = (now - timedelta(days=_retention_years() * 365)).isoformat()
    report: dict = {"dry_run": dry_run, "cutoff_date": cutoff, "deleted": {}}
    with transaction() as con:
        # Quotes: only delete those whose client also has no recent activity
        # (conservative: keep the connection)
        old_quotes = con.execute(
            """SELECT id FROM issued_quotes
               WHERE issued_at < ?
               AND client_name NOT IN (
                 SELECT DISTINCT client_name FROM invoices WHERE created_at >= ?
               )""",
            (cutoff, cutoff),
        ).fetchall()
        report["deleted"]["quotes"] = len(old_quotes)

        # Paid/void invoices past retention with no recent payment activity
        old_invoices = con.execute(
            """SELECT id FROM invoices
               WHERE created_at < ?
               AND status IN ('paid', 'void')
               AND id NOT IN (SELECT invoice_id FROM payments WHERE payment_date >= ?)""",
            (cutoff, cutoff),
        ).fetchall()
        report["deleted"]["invoices"] = len(old_invoices)

        if not dry_run:
            for r in old_quotes:
                con.execute("DELETE FROM issued_quote_items WHERE quote_id = ?", (r["id"],))
                con.execute("DELETE FROM issued_quotes WHERE id = ?", (r["id"],))
            for r in old_invoices:
                con.execute("DELETE FROM invoices WHERE id = ?", (r["id"],))
    return report


def breach_log(event: str, details: dict) -> None:
    """Append to the breach log. POPIA s.22 requires notification to the
    Regulator AND the affected data subject within 72 hours of awareness.
    Use this to start the timeline immediately."""
    try:
        _BREACH_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "event": event,
            "deadline_72h": (datetime.utcnow() + timedelta(hours=72)).isoformat(timespec="seconds") + "Z",
            **details,
        }
        with _BREACH_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
