"""Persistent memory for the QS app.

Captures every user edit and issued quote into a local SQLite DB so the learner
can predict adjustments and surface similar past jobs on future extractions.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from schema import LineItem


DB_PATH = Path(__file__).parent / "data" / "memory.sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_code TEXT,
    description TEXT NOT NULL,
    catalogue_rate REAL NOT NULL,
    user_rate REAL NOT NULL,
    delta_pct REAL NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qty_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_code TEXT,
    description TEXT NOT NULL,
    ai_quantity REAL NOT NULL,
    user_quantity REAL NOT NULL,
    delta_pct REAL NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issued_quotes (
    id TEXT PRIMARY KEY,
    issued_at TEXT NOT NULL,
    total_zar REAL NOT NULL,
    trade_subtotals TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issued_quote_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id TEXT NOT NULL,
    rate_code TEXT,
    trade TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    rate_zar REAL NOT NULL,
    total_zar REAL NOT NULL,
    FOREIGN KEY (quote_id) REFERENCES issued_quotes(id)
);

CREATE INDEX IF NOT EXISTS idx_rate_edits_code ON rate_edits(rate_code);
CREATE INDEX IF NOT EXISTS idx_qty_edits_code ON qty_edits(rate_code);
CREATE INDEX IF NOT EXISTS idx_quote_items_code ON issued_quote_items(rate_code);
"""


_NEW_QUOTE_COLUMNS = [
    ("project", "TEXT"),
    ("quote_name", "TEXT"),
    ("client_name", "TEXT"),
    ("re_subject", "TEXT"),
    ("quote_no", "TEXT"),
    ("labels", "TEXT"),
    ("parent_quote_id", "TEXT"),
]


_NEW_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    vat_reg TEXT,
    address TEXT,
    attention TEXT,
    contact TEXT,
    notes TEXT,
    first_seen TEXT NOT NULL,
    last_used TEXT NOT NULL,
    quote_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects_admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    primary_client TEXT,
    notes TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_used TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learned_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description_norm TEXT UNIQUE NOT NULL,  -- lowercased + stripped — dedup key
    description TEXT NOT NULL,              -- original casing
    trade TEXT NOT NULL,
    subcategory TEXT,                        -- e.g. "Doors", "Skirting"
    unit TEXT NOT NULL,
    median_rate REAL,
    last_rate REAL,
    frequency INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learned_trade ON learned_items(trade);
CREATE INDEX IF NOT EXISTS idx_learned_subcategory ON learned_items(subcategory);
CREATE INDEX IF NOT EXISTS idx_learned_freq ON learned_items(frequency DESC);

-- ============================================================================
-- Invoicing & receivables (Pastel-equivalent for SA construction)
-- ============================================================================
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT UNIQUE NOT NULL,
    client_name TEXT NOT NULL,
    client_address TEXT,
    client_vat_reg TEXT,
    client_attention TEXT,
    project_name TEXT,
    quote_id TEXT,                          -- nullable; set when created from a quote
    invoice_date TEXT NOT NULL,
    due_date TEXT,
    subtotal REAL NOT NULL,                 -- ex-VAT
    vat_pct REAL NOT NULL DEFAULT 15.0,
    vat_amount REAL NOT NULL,
    retention_pct REAL DEFAULT 0,
    retention_amount REAL DEFAULT 0,
    total REAL NOT NULL,                    -- subtotal + vat - retention
    status TEXT NOT NULL DEFAULT 'draft',   -- draft|issued|partial|paid|void
    re_subject TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (quote_id) REFERENCES issued_quotes(id)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    rate REAL NOT NULL,
    amount REAL NOT NULL,
    trade TEXT,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    payment_date TEXT NOT NULL,
    amount REAL NOT NULL,
    method TEXT,                            -- EFT|cash|card|cheque|other
    reference TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_invoices_client ON invoices(client_name);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_quote ON invoices(quote_id);
CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
"""


def _migrate(con: sqlite3.Connection) -> None:
    """Add new columns + tables. Idempotent."""
    existing = {r[1] for r in con.execute("PRAGMA table_info(issued_quotes)").fetchall()}
    for col, ctype in _NEW_QUOTE_COLUMNS:
        if col not in existing:
            con.execute(f"ALTER TABLE issued_quotes ADD COLUMN {col} {ctype}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_issued_quotes_project ON issued_quotes(project)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_issued_quotes_client ON issued_quotes(client_name)")
    con.executescript(_NEW_TABLES_SQL)


_PRAGMAS = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
"""


@contextmanager
def _conn():
    """Default read/write connection. Auto-applies schema, migrations, and PRAGMAs.
    Each call commits on clean exit, rolls back on exception."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_PRAGMAS)
        con.executescript(SCHEMA)
        _migrate(con)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@contextmanager
def transaction():
    """Atomic write context — wraps a BEGIN IMMEDIATE so concurrent writers serialise.
    Use this for any multi-statement write that must be all-or-nothing
    (next_invoice_no + INSERT, record_payment + status recompute, etc.)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_PRAGMAS)
        con.executescript(SCHEMA)
        _migrate(con)
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def backup_to(path: str | Path) -> Path:
    """Atomic, WAL-safe DB backup using SQLite's online backup API.
    Returns the path written to."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        dst = sqlite3.connect(out)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return out


def record_rate_edit(rate_code: Optional[str], description: str, catalogue_rate: float, user_rate: float) -> None:
    if catalogue_rate <= 0 or user_rate <= 0:
        return
    delta_pct = (user_rate - catalogue_rate) / catalogue_rate
    with _conn() as con:
        con.execute(
            "INSERT INTO rate_edits(rate_code, description, catalogue_rate, user_rate, delta_pct, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (rate_code, description, catalogue_rate, user_rate, delta_pct, datetime.utcnow().isoformat()),
        )


def record_qty_edit(rate_code: Optional[str], description: str, ai_quantity: float, user_quantity: float) -> None:
    if ai_quantity <= 0 or user_quantity <= 0:
        return
    delta_pct = (user_quantity - ai_quantity) / ai_quantity
    with _conn() as con:
        con.execute(
            "INSERT INTO qty_edits(rate_code, description, ai_quantity, user_quantity, delta_pct, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (rate_code, description, ai_quantity, user_quantity, delta_pct, datetime.utcnow().isoformat()),
        )


def record_issued_quote(payload: dict, items: Iterable[LineItem]) -> str:
    quote_id = uuid.uuid4().hex[:12]
    header = payload.get("header") or {}
    with _conn() as con:
        con.execute(
            """
            INSERT INTO issued_quotes(
                id, issued_at, total_zar, trade_subtotals, payload,
                project, quote_name, client_name, re_subject, quote_no, labels, parent_quote_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quote_id,
                payload["issued_at"],
                payload["total_zar"],
                json.dumps(payload["trade_subtotals"]),
                json.dumps(payload, default=str),
                (header.get("project") or "").strip() or None,
                (header.get("quote_name") or "").strip() or None,
                (header.get("client_name") or "").strip() or None,
                (header.get("re_subject") or "").strip() or None,
                (header.get("quote_no") or "").strip() or None,
                (header.get("labels") or "").strip() or None,
                (header.get("parent_quote_id") or "").strip() or None,
            ),
        )
        for li in items:
            con.execute(
                "INSERT INTO issued_quote_items(quote_id, rate_code, trade, description, quantity, unit, rate_zar, total_zar) VALUES (?,?,?,?,?,?,?,?)",
                (quote_id, li.rate_code, li.trade, li.description, li.quantity, li.unit, li.rate_zar, li.total_zar),
            )
    return quote_id


def list_quotes(
    project: Optional[str] = None,
    client_name: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    """List issued quotes with optional filters. Returns rows with header metadata."""
    where = []
    params: list = []
    if project:
        where.append("project = ?")
        params.append(project)
    if client_name:
        where.append("client_name = ?")
        params.append(client_name)
    if search:
        where.append("(COALESCE(client_name, '') LIKE ? OR COALESCE(quote_name, '') LIKE ? OR COALESCE(re_subject, '') LIKE ? OR COALESCE(quote_no, '') LIKE ? OR COALESCE(project, '') LIKE ? OR COALESCE(labels, '') LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like, like, like])
    sql = (
        "SELECT id, issued_at, total_zar, project, quote_name, client_name, re_subject, quote_no, labels, parent_quote_id "
        "FROM issued_quotes "
    )
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY issued_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as con:
        return list(con.execute(sql, params).fetchall())


def list_projects() -> list[dict]:
    """Return distinct projects with counts and latest issue date."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                COALESCE(project, '(no project)') AS project,
                COALESCE(client_name, '') AS client_name,
                COUNT(*) AS n,
                MAX(issued_at) AS last_at,
                SUM(total_zar) AS total_zar
            FROM issued_quotes
            GROUP BY COALESCE(project, '(no project)'), COALESCE(client_name, '')
            ORDER BY MAX(issued_at) DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_clients() -> list[dict]:
    """Distinct client names with quote counts and latest activity."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT COALESCE(client_name, '(no client)') AS client_name,
                   COUNT(*) AS n,
                   MAX(issued_at) AS last_at,
                   SUM(total_zar) AS total_zar
            FROM issued_quotes
            GROUP BY COALESCE(client_name, '(no client)')
            ORDER BY MAX(issued_at) DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_client(name: str, vat_reg: str = "", address: str = "", attention: str = "", contact: str = "", notes: str = "") -> None:
    """Insert or update a client by name (case-insensitive match on stored name)."""
    n = (name or "").strip()
    if not n:
        return
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        existing = con.execute("SELECT id, quote_count FROM clients WHERE LOWER(name) = LOWER(?)", (n,)).fetchone()
        if existing:
            con.execute(
                """UPDATE clients SET name=?, vat_reg=?, address=?, attention=?, contact=?, notes=?,
                   last_used=?, quote_count=quote_count+1 WHERE id=?""",
                (n, vat_reg, address, attention, contact, notes, now, existing["id"]),
            )
        else:
            con.execute(
                """INSERT INTO clients(name, vat_reg, address, attention, contact, notes, first_seen, last_used, quote_count)
                   VALUES(?,?,?,?,?,?,?,?,1)""",
                (n, vat_reg, address, attention, contact, notes, now, now),
            )


def list_clients() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT name, vat_reg, address, attention, contact, notes, last_used, quote_count "
            "FROM clients ORDER BY last_used DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_client(name: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT name, vat_reg, address, attention, contact, notes FROM clients WHERE LOWER(name) = LOWER(?)",
            ((name or "").strip(),),
        ).fetchone()
    return dict(row) if row else None


def delete_client(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    with _conn() as con:
        cur = con.execute("DELETE FROM clients WHERE LOWER(name) = LOWER(?)", (n,))
        return cur.rowcount > 0


def upsert_project_admin(name: str, primary_client: str = "", notes: str = "", status: str = "active") -> None:
    n = (name or "").strip()
    if not n:
        return
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        existing = con.execute("SELECT id FROM projects_admin WHERE LOWER(name)=LOWER(?)", (n,)).fetchone()
        if existing:
            con.execute(
                "UPDATE projects_admin SET name=?, primary_client=?, notes=?, status=?, last_used=? WHERE id=?",
                (n, primary_client, notes, status, now, existing["id"]),
            )
        else:
            con.execute(
                """INSERT INTO projects_admin(name, primary_client, notes, status, created_at, last_used)
                   VALUES(?,?,?,?,?,?)""",
                (n, primary_client, notes, status, now, now),
            )


def list_projects_admin() -> list[dict]:
    """Return all manually-created projects + any project names that have been used in quotes."""
    with _conn() as con:
        admin_rows = list(con.execute(
            "SELECT name, primary_client, notes, status, created_at, last_used FROM projects_admin"
        ).fetchall())
        # Also pull project names from issued quotes that aren't in projects_admin
        used_rows = list(con.execute(
            "SELECT DISTINCT project FROM issued_quotes WHERE project IS NOT NULL AND project != ''"
        ).fetchall())
    out = [dict(r) for r in admin_rows]
    seen = {(r.get("name") or "").lower() for r in out}
    for u in used_rows:
        nm = (u["project"] or "").strip()
        if nm and nm.lower() not in seen:
            out.append({"name": nm, "primary_client": "", "notes": "(inferred from past quote)",
                        "status": "active", "created_at": "", "last_used": ""})
    return out


def delete_project_admin(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    with _conn() as con:
        cur = con.execute("DELETE FROM projects_admin WHERE LOWER(name) = LOWER(?)", (n,))
        return cur.rowcount > 0


def upsert_learned_item(description: str, trade: str, unit: str, rate: float, subcategory: str = "") -> None:
    """Add a line item to the learning catalog. Bumps frequency, updates median_rate by simple running average.
    Items with rate=0 are still recorded (so you can fill in a rate later); they just don't update the median."""
    desc = (description or "").strip()
    if not desc:
        return
    norm = desc.lower()
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        existing = con.execute(
            "SELECT id, median_rate, frequency FROM learned_items WHERE description_norm = ?",
            (norm,),
        ).fetchone()
        if existing:
            # Only mix the new rate into the median if it's > 0
            if rate > 0:
                old_median = existing["median_rate"] or rate
                new_median = round((old_median * existing["frequency"] + rate) / (existing["frequency"] + 1), 2)
            else:
                new_median = existing["median_rate"]
            con.execute(
                """UPDATE learned_items SET description=?, trade=?, subcategory=COALESCE(NULLIF(?, ''), subcategory),
                   unit=?, median_rate=?, last_rate=?, frequency=frequency+1, last_seen=?
                   WHERE id=?""",
                (desc, trade, subcategory, unit, new_median, (rate if rate > 0 else existing["median_rate"]),
                 now, existing["id"]),
            )
        else:
            con.execute(
                """INSERT INTO learned_items(description_norm, description, trade, subcategory, unit,
                   median_rate, last_rate, frequency, first_seen, last_seen)
                   VALUES(?,?,?,?,?,?,?,1,?,?)""",
                (norm, desc, trade, subcategory or _suggest_subcategory(desc, trade), unit,
                 (rate if rate > 0 else None), (rate if rate > 0 else None), now, now),
            )


def suggest_next_quote_no(prefix: str = "NPQ") -> str:
    """Look at all past quote_no values starting with `prefix` and return the next one.
    Pattern matches: 'NPQ 7173', 'NPQ-7174', 'NPQ7175' — returns 'NPQ 7176' (with space, ATESS style)."""
    import re
    pat = re.compile(rf"^\s*{re.escape(prefix)}\s*[-_ ]?\s*(\d+)\s*$", re.IGNORECASE)
    max_seen = 0
    with _conn() as con:
        rows = con.execute("SELECT quote_no FROM issued_quotes WHERE quote_no IS NOT NULL").fetchall()
    for r in rows:
        q = (r["quote_no"] or "").strip()
        m = pat.match(q)
        if m:
            try:
                v = int(m.group(1))
                if v > max_seen:
                    max_seen = v
            except ValueError:
                pass
    next_v = max_seen + 1 if max_seen else 7174  # bootstrap from your historical sequence
    return f"{prefix} {next_v}"


def backfill_learned_items_from_quotes() -> int:
    """Sweep every line item ever stored in issued_quote_items into learned_items.
    Use this after upgrades to repopulate the catalog from history. Returns count processed."""
    n = 0
    with _conn() as con:
        rows = con.execute(
            "SELECT description, trade, unit, rate_zar FROM issued_quote_items"
        ).fetchall()
    for r in rows:
        try:
            upsert_learned_item(
                description=r["description"] or "",
                trade=r["trade"] or "other",
                unit=r["unit"] or "no",
                rate=float(r["rate_zar"] or 0.0),
            )
            n += 1
        except Exception:
            continue
    return n


def update_learned_item_subcategory(description_norm: str, subcategory: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "UPDATE learned_items SET subcategory=? WHERE description_norm=?",
            ((subcategory or "").strip() or None, description_norm),
        )
        return cur.rowcount > 0


def update_learned_item_rate(description_norm: str, new_rate: float) -> bool:
    if new_rate is None or float(new_rate) < 0:
        return False
    with _conn() as con:
        cur = con.execute(
            "UPDATE learned_items SET median_rate=?, last_rate=? WHERE description_norm=?",
            (float(new_rate), float(new_rate), description_norm),
        )
        return cur.rowcount > 0


def delete_learned_item(description_norm: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM learned_items WHERE description_norm = ?", (description_norm,))
        return cur.rowcount > 0


def _suggest_subcategory(description: str, trade: str) -> str:
    """Crude keyword-based subcategorization. Improves over time as users edit the field."""
    d = description.lower()
    rules = {
        "drywall":    [("openings", ["window", "door opening"]), ("corners", ["corner", "abutment"]), ("partitions", ["partition", "wall"])],
        "carpentry":  [("doors", ["door"]), ("skirting", ["skirting"]), ("cupboards", ["cupboard", "cabinet", "kitchen"]), ("counters", ["counter", "formica", "top"]), ("brackets", ["bracket"])],
        "tiling":     [("floor", ["floor"]), ("wall", ["wall"]), ("mosaic", ["mosaic"]), ("skirting", ["skirting"])],
        "painting":   [("interior", ["pva", "interior", "wall"]), ("ceiling", ["ceiling"]), ("exterior", ["external", "exterior"]), ("doors", ["door", "enamel"])],
        "plumbing":   [("toilets", ["toilet", "wc"]), ("basins", ["basin"]), ("showers", ["shower"]), ("baths", ["bath"]), ("geysers", ["geyser"])],
        "electrical": [("outlets", ["socket", "plug", "power point"]), ("switches", ["switch"]), ("lighting", ["light", "downlight", "pendant"]), ("DBs", ["db", "distribution"])],
        "pgs":        [("travel", ["travel", "trip"]), ("disposal", ["rubble", "skip", "dispose"]), ("supervision", ["supervisor", "site"])],
    }
    for sub, keywords in rules.get(trade.lower(), []):
        if any(k in d for k in keywords):
            return sub.title()
    return ""


def list_learned_items() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT description, trade, subcategory, unit, median_rate, last_rate, frequency, last_seen "
            "FROM learned_items ORDER BY trade, subcategory, frequency DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_full_quote(quote_id: str) -> Optional[dict]:
    """Return the full payload (header + items + totals) for a stored quote."""
    with _conn() as con:
        row = con.execute("SELECT payload FROM issued_quotes WHERE id = ?", (quote_id,)).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"])
        payload["memory_id"] = quote_id
        return payload
    except Exception:
        return None


def rate_edit_history(rate_code: str, limit: int = 20) -> list[sqlite3.Row]:
    with _conn() as con:
        rows = con.execute(
            "SELECT delta_pct, user_rate, catalogue_rate, ts FROM rate_edits WHERE rate_code = ? ORDER BY id DESC LIMIT ?",
            (rate_code, limit),
        ).fetchall()
    return list(rows)


def qty_edit_history(rate_code: str, limit: int = 20) -> list[sqlite3.Row]:
    with _conn() as con:
        rows = con.execute(
            "SELECT delta_pct, ai_quantity, user_quantity, ts FROM qty_edits WHERE rate_code = ? ORDER BY id DESC LIMIT ?",
            (rate_code, limit),
        ).fetchall()
    return list(rows)


def all_issued_quotes() -> list[sqlite3.Row]:
    with _conn() as con:
        return list(con.execute(
            "SELECT id, issued_at, total_zar, trade_subtotals FROM issued_quotes ORDER BY issued_at DESC"
        ).fetchall())


def items_for_quote(quote_id: str) -> list[sqlite3.Row]:
    with _conn() as con:
        return list(con.execute(
            "SELECT rate_code, trade, description, quantity, unit, rate_zar, total_zar FROM issued_quote_items WHERE quote_id = ?",
            (quote_id,),
        ).fetchall())


def summary_stats() -> dict:
    with _conn() as con:
        return {
            "rate_edits": con.execute("SELECT COUNT(*) FROM rate_edits").fetchone()[0],
            "qty_edits": con.execute("SELECT COUNT(*) FROM qty_edits").fetchone()[0],
            "issued_quotes": con.execute("SELECT COUNT(*) FROM issued_quotes").fetchone()[0],
        }


def rate_edit_aggregates() -> list[dict]:
    """Per-rate-code edit aggregates — sample size, median delta, latest delta."""
    with _conn() as con:
        rows = con.execute("""
            SELECT rate_code,
                   COUNT(*) AS n,
                   AVG(delta_pct) AS mean_delta,
                   MAX(ts) AS last_ts
            FROM rate_edits
            WHERE rate_code IS NOT NULL
            GROUP BY rate_code
        """).fetchall()
    return [
        {"rate_code": r["rate_code"], "n": r["n"], "mean_delta": r["mean_delta"], "last_ts": r["last_ts"]}
        for r in rows
    ]
