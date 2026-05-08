"""Audit log tab — read-only chronological view of every action this session.

Intentionally minimal: code-style fixed-width entries are the right shape
for a developer/auditor scanning by eye. No filters, no pagination yet.
"""
from __future__ import annotations

import json

import streamlit as st


def render(ss) -> None:
    st.subheader("Audit log")
    st.caption(
        "Every quantity/rate change, confirmation, lock, undo, and issue. "
        "Persisted for the session."
    )
    if not ss.audit_log:
        st.info("No audit entries yet.")
        return
    for e in reversed(ss.audit_log):
        ts = e["ts"]
        action = e["action"]
        iid = e.get("item_id") or ""
        details = e.get("details") or {}
        st.code(
            f"{ts}  {action:<22} {iid:<10} {json.dumps(details, default=str)}",
            language=None,
        )
