"""Persistent company profile — Ndlovu's vendor info, payment terms, banking.

Saved to data/company_profile.json. If the file doesn't exist yet, the built-in
NDLOVU_DEFAULT below is used so the PDF always renders correctly with the
authoritative vendor block — even on a fresh Pi or after wiping data/.

Only client-specific and quote-specific fields reset per job. Ndlovu's vendor
info is "system-default" and survives DB resets.
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_PATH = Path(__file__).parent / "data" / "company_profile.json"

# ----------------------------------------------------------------------------
# Built-in default — the canonical Ndlovu T Projects vendor block. Captured
# from NPQ 7624 (the reference quote). Used whenever no saved profile exists.
# ----------------------------------------------------------------------------
NDLOVU_DEFAULT: dict = {
    "company_name": "NDLOVU T PROJECTS (PTY) LTD",
    "company_address": "P.O. Box 702, Bergbron, 1719",
    "company_phone_robert": "+27 76 044 7331 (Robert)",
    "company_phone_tina":   "+27 73 026 9037 (Tina)",
    "company_email_robert": "robert@ndlovuprojects.co.za",
    "company_email_tina":   "tina@ndlovuprojects.co.za",
    "company_reg":     "2011/135937/07",
    "company_vat_reg": "4700263249",
    # Composite contact line for older quote-header forms
    "company_contact": "+27 76 044 7331 (Robert) | +27 73 026 9037 (Tina)",
    "payment_terms": "50% Deposit\n50% Final on completion",
    "banking_details": (
        "Name: Ndlovu T Projects (Pty) Ltd\n"
        "Branch: ABSA Bank\n"
        "Account No: 4078849715\n"
        "Branch Code: 632 005"
    ),
    # Plascon-applicator footer renders when this is truthy
    "plascon_applicator_year": "2026",
    "vat_pct": 15,
    "show_vat": True,
    # Standard SA QS contract clauses — match NPQ 7624 verbatim
    "conditions": [
        "This quote is valid for 15 business days only.",
        "This quote includes VAT.",
        "Only the work as specified herein will be carried out. Any additional work must have a written order.",
        "On acceptance of this quote, please provide your company order number.",
        "No work shall commence until the deposit is paid in full. Subsequent payments are payable within 5 business days from date of invoice.",
        "Should payment not be received in full within 5 business days from date of invoice, we reserve the right to institute legal proceedings against you for the recovery of the outstanding amount, together with the interest thereon at the prescribed rate of interest from date of default to payment in full; as well as all legal costs on the scale of attorney and own client and collection commissions incurred.",
        "Until such time as the project price is paid in full, ownership in the project and all legal and beneficial rights thereto remain vested in ourselves.",
        "Any failure or neglect to enforce any of our rights in terms of this quotation does not constitute a waiver thereof.",
        "In the event of any dispute, you consent to the jurisdiction of the Magistrate's Court in terms of section 45 of the Magistrate's Court Act 32 of 1944.",
    ],
    "thank_you_paragraph": (
        "We thank you for the opportunity to submit our quote at the above-mentioned premises and assure you of "
        "our best attention and service at all times."
    ),
    "acceptance_block": "PLEASE COMPLETE, SIGN AND RETURN ON ACCEPTANCE OF QUOTE",
}


# Fields that persist across jobs — these are "yours" not the customer's.
PERSISTENT_FIELDS = list(NDLOVU_DEFAULT.keys())


def load_profile() -> dict:
    """Load saved company profile, falling back to the canonical Ndlovu default
    so the PDF always has the authoritative vendor block — even on a fresh
    install or after `data/` is wiped."""
    if not PROFILE_PATH.exists():
        return dict(NDLOVU_DEFAULT)
    try:
        saved = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(NDLOVU_DEFAULT)
    # Layer saved on top of defaults so any missing fields fall through cleanly
    out = dict(NDLOVU_DEFAULT)
    for k, v in saved.items():
        if v not in (None, "", []):
            out[k] = v
    return out


def save_profile(profile: dict) -> None:
    """Persist the persistent subset of fields to disk."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    persistent = {k: profile.get(k) for k in PERSISTENT_FIELDS if k in profile}
    PROFILE_PATH.write_text(json.dumps(persistent, indent=2), encoding="utf-8")


def merge_into_header(header: dict) -> dict:
    """Apply persistent fields to a header dict, leaving per-job fields alone.
    Saved values win over header defaults so 'your' details always reflect disk
    (or built-in default) state."""
    saved = load_profile()
    out = dict(header)
    for k, v in saved.items():
        if v not in (None, "", []):
            out[k] = v
    return out
