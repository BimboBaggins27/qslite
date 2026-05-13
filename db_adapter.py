"""Database connection adapter — switches between local SQLite and Turso (libSQL).

When TURSO_URL and TURSO_AUTH_TOKEN are set, returns a libsql-backed
connection wrapped so its rows behave like sqlite3.Row (dict-style and
index-style access). libsql 0.1.11 returns tuples and ignores row_factory,
so we wrap it.

Falls back to local sqlite3 when Turso env vars are missing.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

LOCAL_DB_PATH = Path(__file__).parent / "data" / "memory.sqlite"

_TURSO_URL = os.getenv("TURSO_URL", "").strip()
_TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
USE_TURSO = bool(_TURSO_URL and _TURSO_TOKEN)


def _normalised_turso_url() -> str:
    """Force https:// scheme — libsql:// defaults to wss which Turso 2026 rejects (HTTP 505)."""
    url = _TURSO_URL
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url


class _TursoRow:
    """sqlite3.Row-compatible row: r['col'] and r[0] both work."""
    __slots__ = ("_data", "_cols")

    def __init__(self, data: tuple, cols: list[str]) -> None:
        self._data = data
        self._cols = cols

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._data[key]
        try:
            return self._data[self._cols.index(key)]
        except ValueError as e:
            raise KeyError(key) from e

    def keys(self) -> list[str]:
        return list(self._cols)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"<Row {dict(zip(self._cols, self._data))}>"


class _TursoCursor:
    """Wraps libsql.Cursor; converts tuples to _TursoRow for fetch* methods."""

    def __init__(self, libsql_cursor) -> None:
        self._cur = libsql_cursor

    @property
    def _cols(self) -> list[str]:
        d = self._cur.description or ()
        return [c[0] for c in d]

    @property
    def rowcount(self) -> int:
        return getattr(self._cur, "rowcount", -1)

    @property
    def lastrowid(self) -> int:
        return getattr(self._cur, "lastrowid", 0)

    @property
    def description(self):
        return self._cur.description

    def fetchone(self) -> Optional[_TursoRow]:
        r = self._cur.fetchone()
        if r is None:
            return None
        return _TursoRow(tuple(r), self._cols)

    def fetchall(self) -> list[_TursoRow]:
        cols = self._cols
        return [_TursoRow(tuple(r), cols) for r in self._cur.fetchall()]

    def fetchmany(self, size: int = 1) -> list[_TursoRow]:
        cols = self._cols
        return [_TursoRow(tuple(r), cols) for r in self._cur.fetchmany(size)]

    def __iter__(self):
        return iter(self.fetchall())

    def close(self) -> None:
        try:
            self._cur.close()
        except Exception:
            pass


class _TursoConnection:
    """Wraps libsql.Connection. Returns _TursoCursor from execute()."""

    def __init__(self, libsql_con) -> None:
        self._con = libsql_con
        self.row_factory = None  # accepted but ignored — we always return _TursoRow

    def execute(self, sql: str, params: Iterable[Any] = ()) -> _TursoCursor:
        plist = list(params) if params else []
        cur = self._con.execute(sql, plist) if plist else self._con.execute(sql)
        return _TursoCursor(cur)

    def executescript(self, script: str) -> None:
        """Delegate to libsql's native executescript, after stripping local-only PRAGMAs."""
        import re
        # libsql ignores or rejects these — strip them out per line
        skip_prefixes = ("pragma journal_mode", "pragma synchronous", "pragma busy_timeout")
        cleaned_lines = []
        for line in script.splitlines():
            stripped = line.strip().lower()
            if any(stripped.startswith(p) for p in skip_prefixes):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)
        self._con.executescript(cleaned)

    def executemany(self, sql: str, seq) -> None:
        self._con.executemany(sql, list(seq))

    def commit(self) -> None:
        try:
            self._con.commit()
        except Exception:
            pass

    def rollback(self) -> None:
        try:
            self._con.rollback()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._con.close()
        except Exception:
            pass


def connect() -> Any:
    """Return a connection. Both backends expose the same API:
    .execute, .executescript, .commit, .rollback, .close.
    Rows support sqlite3.Row-style access — r['col'] and r[0] both work.
    """
    if USE_TURSO:
        import libsql
        raw = libsql.connect(
            database=_normalised_turso_url(),
            auth_token=_TURSO_TOKEN,
        )
        return _TursoConnection(raw)
    LOCAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LOCAL_DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con


def diagnostic() -> dict:
    """Return where data is currently being read/written from."""
    if USE_TURSO:
        host = _TURSO_URL.replace("libsql://", "").replace("https://", "").split("/")[0]
        return {"mode": "turso", "host": host, "local_fallback": str(LOCAL_DB_PATH)}
    return {"mode": "local-sqlite", "path": str(LOCAL_DB_PATH), "exists": LOCAL_DB_PATH.exists()}
