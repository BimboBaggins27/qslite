"""One-shot migration: copy every row from local sqlite -> Turso (libSQL).

Usage:
    1. Set TURSO_URL and TURSO_AUTH_TOKEN in qs-app/.env (production) or qs-app-staging/.env (test)
    2. Run from the directory that contains memory.py:
         python migrate_to_turso.py [--source PATH] [--dry-run]
    3. Verify the row-count summary matches between source and destination.

The script is idempotent — re-running it does a DELETE FROM each table on Turso
first, then re-inserts. Safe to run multiple times during testing.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Load .env BEFORE db_adapter, which reads TURSO_URL/TOKEN at import time
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Import the adapter that knows about Turso
import db_adapter

TABLES = [
    "rate_edits",
    "qty_edits",
    "issued_quotes",
    "issued_quote_items",
    "clients",
    "projects_admin",
    "learned_items",
    "invoices",
    "invoice_lines",
    "payments",
]


def _src_path(custom: str | None) -> Path:
    if custom:
        p = Path(custom)
    else:
        p = Path(__file__).parent / "data" / "memory.sqlite"
    if not p.exists():
        sys.exit(f"Source SQLite DB not found: {p}")
    return p


def _ensure_schema_remote() -> None:
    """Import memory module so its SCHEMA + _migrate run against the remote DB."""
    import memory  # noqa: F401 — importing triggers schema bootstrap on first _conn()
    with memory._conn() as _:
        pass


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _row_count_local(con: sqlite3.Connection, table: str) -> int:
    if not _table_exists(con, table):
        return 0
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _row_count_remote(table: str) -> int:
    import memory
    with memory._conn() as con:
        try:
            r = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return int(r[0]) if r else 0
        except Exception:
            return 0


def _copy_table(src: sqlite3.Connection, table: str, dry_run: bool) -> tuple[int, int]:
    """Copy all rows from local sqlite to Turso. Returns (read, written)."""
    if not _table_exists(src, table):
        return (0, 0)
    src.row_factory = sqlite3.Row
    rows = list(src.execute(f"SELECT * FROM {table}").fetchall())
    if not rows:
        return (0, 0)
    cols = list(rows[0].keys())
    col_list = ",".join(cols)
    placeholders = ",".join("?" for _ in cols)

    if dry_run:
        return (len(rows), 0)

    import memory
    with memory._conn() as remote:
        remote.execute(f"DELETE FROM {table}")
        for r in rows:
            remote.execute(
                f"INSERT INTO {table}({col_list}) VALUES ({placeholders})",
                tuple(r[c] for c in cols),
            )
    return (len(rows), len(rows))


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate local sqlite -> Turso")
    ap.add_argument("--source", help="Path to source memory.sqlite (default: ./data/memory.sqlite)")
    ap.add_argument("--dry-run", action="store_true", help="Read counts only, write nothing")
    args = ap.parse_args()

    if not db_adapter.USE_TURSO:
        sys.exit("TURSO_URL / TURSO_AUTH_TOKEN not set — nothing to migrate to.")

    src_path = _src_path(args.source)
    print(f"Source : {src_path}")
    print(f"Target : {db_adapter._TURSO_URL}")
    print(f"Dry-run: {args.dry_run}")
    print()

    print("Ensuring remote schema...")
    _ensure_schema_remote()

    src = sqlite3.connect(src_path)

    print(f"{'Table':<24} {'Local':>10} {'Wrote':>10} {'Remote':>10}")
    print("-" * 60)
    total_local = total_written = total_remote = 0
    for t in TABLES:
        local = _row_count_local(src, t)
        _, written = _copy_table(src, t, dry_run=args.dry_run)
        remote = _row_count_remote(t)
        total_local += local
        total_written += written
        total_remote += remote
        print(f"{t:<24} {local:>10} {written:>10} {remote:>10}")
    print("-" * 60)
    print(f"{'TOTAL':<24} {total_local:>10} {total_written:>10} {total_remote:>10}")

    src.close()

    if not args.dry_run and total_local != total_remote:
        print("\nWARNING: row counts differ between source and target.", file=sys.stderr)
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
