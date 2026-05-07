"""Persistent company profile — your banking details, company info, payment terms.

Saved to data/company_profile.json so it survives server restarts and browser sessions.
Only client-specific and quote-specific fields reset per job.
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_PATH = Path(__file__).parent / "data" / "company_profile.json"

# Fields that persist across jobs — these are "yours" not the customer's.
PERSISTENT_FIELDS = [
    "company_name",
    "company_vat_reg",
    "company_address",
    "company_contact",
    "payment_terms",
    "banking_details",
    "acceptance_block",
    "vat_pct",
    "show_vat",
]


def load_profile() -> dict:
    """Load saved company profile. Returns {} if not yet saved."""
    if not PROFILE_PATH.exists():
        return {}
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_profile(profile: dict) -> None:
    """Save persistent fields only — strip out any client/quote stuff that slips in."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    persistent = {k: profile.get(k) for k in PERSISTENT_FIELDS if k in profile}
    PROFILE_PATH.write_text(json.dumps(persistent, indent=2), encoding="utf-8")


def merge_into_header(header: dict) -> dict:
    """Apply saved persistent fields to a header dict, leaving per-job fields alone.
    Saved values win over header defaults so 'your' details always reflect disk state."""
    saved = load_profile()
    out = dict(header)
    for k, v in saved.items():
        if v not in (None, "", []):
            out[k] = v
    return out
