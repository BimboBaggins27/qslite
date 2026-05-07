"""In-session version history for line items.

Lightweight snapshot stack — every mutation that the UI cares about pushes a
copy of the current line-items list onto the history. `undo()` pops the most
recent snapshot back into place.

Versioning is in-session memory only (Streamlit `session_state`). For cross-
session quote history, an issued quote is the durable record (see memory.py).
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from schema import LineItem


HISTORY_LIMIT = 50


def snapshot(history: list[dict], items: list[LineItem], label: str) -> None:
    """Push a deep copy of items onto the history stack."""
    history.append({
        "ts": datetime.utcnow().isoformat(timespec="seconds"),
        "label": label,
        "items": [li.model_copy(deep=True) for li in items],
    })
    # Cap history
    if len(history) > HISTORY_LIMIT:
        del history[: len(history) - HISTORY_LIMIT]


def undo(history: list[dict]) -> tuple[list[LineItem] | None, str | None]:
    """Pop the most recent snapshot. Returns (restored_items, label) or (None, None)."""
    if not history:
        return None, None
    entry = history.pop()
    return entry["items"], entry["label"]


def can_undo(history: list[dict]) -> bool:
    return len(history) > 0


def last_label(history: list[dict]) -> str | None:
    return history[-1]["label"] if history else None
