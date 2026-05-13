from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import streamlit as st

import company_profile
import demo_extractor
import invoices
import key_manager
import learner
import memory
import providers
import rate_review
import validators
import versioning
from invoice_pdf import render_invoice_pdf, render_statement_pdf
from excel import issued_quote_to_xlsx
from extract import (
    extract_diff_from_files,
    extract_elements,
    extract_elements_from_pdf,
    pdf_pages_to_pngs,
)
from pdf_render import render_quote_pdf
from quote import (
    audit,
    blocker_summary,
    can_issue,
    freeze_quote,
    line_items_from_extraction,
    quote_total,
    trade_subtotals,
)
from rates import load_rates
from schema import EditState, LineItem, Provenance, QuoteHeader
import survey_template

try:
    from streamlit_mic_recorder import speech_to_text as _stt
except Exception:
    _stt = None

try:
    from streamlit_paste_button import paste_image_button
except Exception:
    paste_image_button = None

# Lucide icons — inline SVG (replaces emoji where Streamlit allows raw HTML)
try:
    from lucide_icons import icon as ic, icon_label as il
except Exception:
    def ic(name: str, size: int = 18, color: str = "currentColor") -> str: return ""
    def il(name: str, label: str, size: int = 18, color: str = "currentColor") -> str: return label

try:
    from voice_edits import parse_voice_instruction, apply_edits as _apply_voice_edits
except Exception:
    parse_voice_instruction = None
    _apply_voice_edits = None

try:
    from video_frames import extract_video_keyframes, is_video_filename, VIDEO_EXTS
except Exception:
    extract_video_keyframes = None
    def is_video_filename(name: str) -> bool: return False
    VIDEO_EXTS = set()


st.set_page_config(
    page_title="QS Live — Quotation Studio",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="collapsed",  # tap the » arrow to open when you need API key / Undo / zone locks
)

# ---------- iOS PWA install support (Path A: home-screen install via Safari) ----------
def _embed_ios_pwa_meta() -> None:
    """Inject the meta tags Safari needs for 'Add to Home Screen' to behave like an installed app."""
    import base64
    icon_path = Path(__file__).parent / "assets" / "icon-180.png"
    icon_b64 = ""
    if icon_path.exists():
        icon_b64 = base64.b64encode(icon_path.read_bytes()).decode("ascii")
    apple_icon = f"data:image/png;base64,{icon_b64}" if icon_b64 else ""
    st.markdown(
        f"""
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="Ndlovu QS">
        <meta name="theme-color" content="#0A2540">
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
        <link rel="apple-touch-icon" sizes="180x180" href="{apple_icon}">
        <link rel="apple-touch-icon" sizes="192x192" href="{apple_icon}">
        """,
        unsafe_allow_html=True,
    )


_embed_ios_pwa_meta()


# ---------- Password gate (rate-limited, audited, identity-header-aware) ----------
from auth import site_password_gate
site_password_gate()

# ---------- visual polish ----------
LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
LOGO_PATH.parent.mkdir(parents=True, exist_ok=True)
if LOGO_PATH.exists():
    try:
        st.logo(str(LOGO_PATH))
    except Exception:
        pass

_QSLITE_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* QSLite v3 design system — synthesized from Linear / Stripe / Vercel / Cal.com.
   Linear-flavored "modern conservative" — quiet, dense, hairline borders. */

:root {
    /* Surfaces — warm-cool neutral */
    --bg          : #FAFAF9;
    --bg-card     : #FFFFFF;
    --bg-subtle   : #F4F4F2;

    /* Ink — near-black, never #000 */
    --ink         : #18181B;
    --ink-2       : #52525B;
    --ink-3       : #8A8F98;

    /* Borders — hairline, never heavy */
    --line        : #E5E5E6;
    --line-strong : #D4D4D8;

    /* Brand — single saturated accent (Linear indigo) */
    --brand       : #5E6AD2;
    --brand-hover : #4F5ABF;
    --brand-soft  : #EEF0FB;

    /* Semantic — muted, not candy */
    --success     : #15803D;
    --success-soft: #ECFDF5;
    --warn        : #B45309;
    --warn-soft   : #FFFBEB;
    --danger      : #B91C1C;
    --danger-soft : #FEF2F2;
    --info        : #1D4ED8;
    --info-soft   : #EFF6FF;

    /* Spacing scale */
    --s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px;
    --s-5: 20px; --s-6: 24px; --s-8: 32px; --s-10: 40px;

    /* Radius */
    --r-sm: 4px; --r-md: 6px; --r-lg: 8px; --r-xl: 12px;

    /* Shadows — borders do most of the lifting */
    --shadow-sm: 0 1px 2px rgba(16,24,40,.04);
    --shadow-md: 0 4px 12px rgba(16,24,40,.06), 0 1px 2px rgba(16,24,40,.04);
}

/* Page chrome */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, "Segoe UI", Roboto, sans-serif !important;
    -webkit-font-smoothing: antialiased;
    color: var(--ink);
}
.stApp, [data-testid="stAppViewContainer"] {
    background: var(--bg) !important;
}
[data-testid="stHeader"] {
    background: rgba(250,250,249,0.85) !important;
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--line);
}
.block-container {
    padding-top: 1.2rem !important;
    max-width: 1280px;
}

code, pre {
    font-family: 'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace !important;
    font-size: 0.85em;
}

/* Typography — tight 4-step scale */
h1, h2, h3, h4 { color: var(--ink); letter-spacing: -0.015em; font-weight: 600; }
h1 { font-size: 1.5rem !important; line-height: 1.3; font-weight: 700; }
h2 { font-size: 1.125rem !important; line-height: 1.4; }
h3 { font-size: 1rem !important; line-height: 1.4; }
.stMarkdown p { color: var(--ink); font-size: 0.9rem; line-height: 1.55; }

/* Tabular numerals on amount cells */
.amount, [class*="amount"] {
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
}

/* Page header card (Xero pattern, no gradient) */
.qs-page-header {
    display: flex; align-items: flex-end; justify-content: space-between;
    gap: var(--s-4); padding: var(--s-5) var(--s-6) var(--s-4);
    margin-bottom: var(--s-5);
    background: var(--bg-card); border: 1px solid var(--line);
    border-radius: var(--r-lg);
}
.qs-page-header__title { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.qs-page-header__eyebrow {
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--brand);
}
.qs-page-header__h1 {
    font-size: 1.5rem; font-weight: 700; line-height: 1.2;
    letter-spacing: -0.02em; color: var(--ink); margin: 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.qs-page-header__subtitle {
    font-size: 0.875rem; color: var(--ink-2); margin-top: 2px;
}
.qs-page-header__meta { display: flex; align-items: center; gap: var(--s-2); flex-shrink: 0; }

/* Cards — border-first, no hover-lift */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--line) !important;
    border-radius: var(--r-lg) !important;
    padding: var(--s-4) !important;
    box-shadow: none;
    transition: none;
}

/* Buttons — 40px touch, flat solid primary, no gradient */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
    height: 40px;
    padding: 0 var(--s-4) !important;
    border-radius: var(--r-md) !important;
    font: 500 14px/1 'Inter', sans-serif !important;
    background: var(--bg-card) !important;
    color: var(--ink) !important;
    border: 1px solid var(--line-strong) !important;
    box-shadow: none;
    transition: background 120ms ease, border-color 120ms ease;
    min-height: 40px;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
    background: var(--bg-subtle) !important;
    border-color: var(--ink-3) !important;
    transform: none;
    box-shadow: none;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background: var(--brand) !important;
    color: #FFFFFF !important;
    border: 1px solid var(--brand) !important;
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
    background: var(--brand-hover) !important;
    border-color: var(--brand-hover) !important;
    transform: none;
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
    opacity: 0.5; cursor: not-allowed; background: var(--bg-subtle) !important;
}

/* Sidebar — light, flat, no gradient */
[data-testid="stSidebar"] {
    background: var(--bg-card) !important;
    border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] *, [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4 {
    color: var(--ink) !important;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    color: var(--ink-3) !important;
}
[data-testid="stSidebar"] .stButton > button { background: var(--bg-card) !important; }
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: var(--brand) !important; color: #FFFFFF !important;
}

/* Tabs — clean underline indicator */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px; border-bottom: 1px solid var(--line) !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab"] {
    font-weight: 500; font-size: 0.95rem; padding: 12px 16px !important;
    border-radius: 0 !important; background: transparent !important;
    border: none !important; border-bottom: 2px solid transparent !important;
    color: var(--ink-3) !important; transition: color 120ms;
    margin-bottom: -1px;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--ink) !important; background: var(--bg-subtle) !important; }
.stTabs [aria-selected="true"] {
    color: var(--brand) !important; border-bottom-color: var(--brand) !important;
    font-weight: 600;
}

/* Metrics */
[data-testid="stMetric"] {
    background: var(--bg-card); padding: var(--s-4) var(--s-5);
    border-radius: var(--r-lg); border: 1px solid var(--line);
    box-shadow: none;
}
[data-testid="stMetric"]:hover { box-shadow: none; transform: none; }
[data-testid="stMetricLabel"] {
    font-size: 0.72rem !important; color: var(--ink-3) !important;
    font-weight: 600 !important; text-transform: uppercase; letter-spacing: 0.06em;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important; font-weight: 700 !important;
    color: var(--ink) !important; letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
}

/* Inputs */
.stTextInput input, .stTextArea textarea, .stNumberInput input {
    border-radius: var(--r-md) !important;
    border: 1px solid var(--line-strong) !important;
    background: var(--bg-card) !important;
    color: var(--ink) !important;
    padding: 8px 12px !important;
    min-height: 40px;
    transition: border-color 120ms, box-shadow 120ms;
}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
    border-color: var(--brand) !important;
    box-shadow: 0 0 0 3px rgba(94,106,210,0.15) !important;
    outline: none !important;
}
.stTextInput label, .stTextArea label, .stNumberInput label,
.stSelectbox label, .stRadio label {
    font-weight: 500 !important; color: var(--ink-2) !important;
    font-size: 0.82rem !important;
}

/* Dropdowns */
[data-baseweb="select"] > div {
    background: var(--bg-card) !important;
    color: var(--ink) !important;
    border-radius: var(--r-md) !important;
    border-color: var(--line-strong) !important;
    min-height: 40px;
}
[data-baseweb="popover"] {
    background: var(--bg-card) !important;
    border-radius: var(--r-lg) !important;
    box-shadow: var(--shadow-md) !important;
    border: 1px solid var(--line);
}
[data-baseweb="popover"] [role="option"] {
    font-size: 13px !important; padding: 8px 12px !important;
    color: var(--ink) !important; border-radius: var(--r-sm);
}
[data-baseweb="popover"] [role="option"]:hover {
    background: var(--brand-soft) !important; color: var(--brand) !important;
}
[data-baseweb="popover"] [role="option"][aria-selected="true"] {
    background: var(--brand-soft) !important; color: var(--brand) !important;
    font-weight: 600 !important;
}
[data-baseweb="tag"] {
    background: var(--brand-soft) !important; color: var(--brand) !important;
    border-radius: var(--r-sm) !important; font-weight: 500;
}

/* Status pills (Stripe pattern: dot + soft bg + dark text) */
.qs-pill {
    display: inline-flex; align-items: center; gap: 6px;
    height: 22px; padding: 0 8px;
    border-radius: var(--r-sm);
    font-size: 12px; font-weight: 500; line-height: 1;
    font-variant-numeric: tabular-nums;
}
.qs-pill::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%;
}
.qs-pill-grey   { background: var(--bg-subtle);    color: var(--ink-2); }
.qs-pill-grey::before   { background: var(--ink-3); }
.qs-pill-info   { background: var(--info-soft);    color: var(--info); }
.qs-pill-info::before   { background: var(--info); }
.qs-pill-amber  { background: var(--warn-soft);    color: var(--warn); }
.qs-pill-amber::before  { background: var(--warn); }
.qs-pill-green  { background: var(--success-soft); color: var(--success); }
.qs-pill-green::before  { background: var(--success); }
.qs-pill-red    { background: var(--danger-soft);  color: var(--danger); }
.qs-pill-red::before    { background: var(--danger); }
.qs-pill-brand  { background: var(--brand-soft);   color: var(--brand); }
.qs-pill-brand::before  { background: var(--brand); }

/* Card / strip / dropzone scaffolding kept for reuse */
.qs-card {
    background: var(--bg-card); border: 1px solid var(--line);
    border-radius: var(--r-lg); padding: var(--s-4);
    box-shadow: var(--shadow-sm);
}
.qs-strip {
    display: flex; flex-wrap: wrap; gap: var(--s-4);
    background: var(--bg-card); border: 1px solid var(--line);
    border-radius: var(--r-lg); padding: var(--s-3) var(--s-4);
    margin-bottom: var(--s-3);
    box-shadow: none;
}
.qs-strip-cell {
    display: flex; flex-direction: column;
    padding-right: var(--s-4); border-right: 1px solid var(--line);
}
.qs-strip-cell:last-child { border-right: none; padding-right: 0; }
.qs-strip-label {
    color: var(--ink-3); font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500;
}
.qs-strip-value { font-weight: 600; color: var(--ink); font-size: 0.92rem; }

/* Captions */
[data-testid="stCaptionContainer"], small.qs-caption {
    color: var(--ink-3) !important;
    font-size: 0.82rem !important;
    line-height: 1.5;
}

/* Expanders — flat, hairline */
[data-testid="stExpander"] {
    background: var(--bg-card);
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    margin-bottom: var(--s-2);
    box-shadow: none;
    transition: none;
}
[data-testid="stExpander"]:hover { box-shadow: none; }
[data-testid="stExpander"] summary {
    padding: 10px 14px !important;
    font-weight: 500;
    color: var(--ink);
}
[data-testid="stExpander"] summary:hover { background: var(--bg-subtle); }
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    padding: 12px 16px 14px !important;
    background: var(--bg-card);
}

/* Sticky bottom action card */
.qs-sticky-action {
    position: sticky; bottom: 0; z-index: 30;
    background: linear-gradient(180deg, rgba(250,250,249,0) 0%, rgba(250,250,249,0.95) 30%, var(--bg) 100%);
    padding: var(--s-3) var(--s-1) var(--s-4);
    margin-top: var(--s-3);
    border-top: 1px solid var(--line);
}
.qs-divider {
    height: 1px;
    background: var(--line);
    margin: var(--s-4) 0;
}

/* Floating scroll-to-top — neutral, NOT a competing CTA */
.qs-totop {
    position: fixed; right: 22px; bottom: 22px;
    width: 36px; height: 36px;
    border-radius: 50%;
    background: var(--bg-card);
    color: var(--ink-2) !important;
    text-decoration: none;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem; font-weight: 600;
    border: 1px solid var(--line-strong);
    box-shadow: var(--shadow-sm);
    transition: background 120ms;
    z-index: 40;
}
.qs-totop:hover { background: var(--bg-subtle); }
@media (max-width: 768px) { .qs-totop { display: none; } }

/* Alerts */
[data-testid="stAlert"] {
    border-radius: var(--r-lg) !important;
    border: 1px solid var(--line) !important;
    box-shadow: none;
}

/* Tables */
[data-testid="stDataFrame"] {
    border-radius: var(--r-lg);
    overflow: hidden;
    border: 1px solid var(--line);
    box-shadow: none;
}

/* Mobile — proper iPad portrait + small-screen behavior */
@media (max-width: 768px) {
    .qs-page-header { flex-direction: column; align-items: flex-start; padding: var(--s-3) var(--s-4); }
    .qs-page-header__h1 { font-size: 1.2rem; }
    h1 { font-size: 1.25rem !important; }
    [data-testid="column"] { width: 100% !important; flex: 0 0 100% !important; }
    .stButton > button, .stDownloadButton > button { padding: 0 12px !important; min-height: 40px; }
    .stTextInput input, .stTextArea textarea, .stNumberInput input {
        font-size: 16px !important;  /* prevents iOS zoom-on-focus */
        min-height: 40px;
    }
    .stTabs [data-baseweb="tab-list"] { overflow-x: auto; flex-wrap: nowrap; }
    .stTabs [data-baseweb="tab"] { white-space: nowrap; padding: 12px 14px !important; font-size: 0.92rem; }
    .block-container { padding-top: 0.8rem !important; padding-left: 0.6rem; padding-right: 0.6rem; }
}
</style>
"""

# st.html() injects raw HTML without markdown processing — avoids the leading-
# whitespace-as-code-block trap that bit us when we used st.markdown for CSS.
st.html(_QSLITE_CSS)

# ---------- session state ----------

ss = st.session_state
ss.setdefault("line_items", [])
ss.setdefault("audit_log", [])
ss.setdefault("frozen_quote", None)
ss.setdefault("uploads", {})
ss.setdefault("learner_hints", {})
ss.setdefault("ai_baseline", {})
ss.setdefault("pending_items", [])  # items awaiting diff-confirm
ss.setdefault("locked_zones", set())  # zones the user has locked from re-extraction
ss.setdefault("history", [])  # versioning stack
ss.setdefault("quote_header", QuoteHeader().model_dump())  # editable cover-page fields
ss.setdefault("key_input_seq", 0)  # increment to force a fresh API-key input widget
ss.setdefault("ctx_seq", 0)  # increment to refresh the context textarea after STT injection
ss.setdefault("ctx_buffer", "")  # buffer that backs the context textarea
ss.setdefault("voice_seq", 0)  # rotates voice-edit widget keys
ss.setdefault("voice_edit_pending", None)  # holds parsed edits awaiting user confirmation
# ---- Work folder (where issued quotes auto-save) ----
_WORK_FOLDER_FILE = Path(__file__).parent / "data" / ".work_folder"
def _load_work_folder() -> str:
    if _WORK_FOLDER_FILE.exists():
        try:
            v = _WORK_FOLDER_FILE.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return r"E:\NdlovuQS"
def _save_work_folder(p: str) -> None:
    _WORK_FOLDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WORK_FOLDER_FILE.write_text(p.strip(), encoding="utf-8")
ss.setdefault("work_folder", _load_work_folder())


def log(action: str, item_id: str | None = None, **details) -> None:
    ss.audit_log.append(audit("user", action, item_id, **details).model_dump())


def take_snapshot(label: str) -> None:
    versioning.snapshot(ss.history, ss.line_items, label)


# ---------- Ruflo-inspired UI primitives ----------

def _pill(label: str, kind: str = "grey") -> str:
    """Return inline HTML for a status pill. kind: green / amber / red / info / grey."""
    return f'<span class="qs-pill qs-pill-{kind}">{label}</span>'


def _strip_cell(label: str, value: str, pill: Optional[str] = None) -> str:
    inner = f'<span class="qs-strip-label">{label}</span>'
    inner += f' <span class="qs-strip-value">{value}</span>'
    if pill:
        inner += f' {pill}'
    return f'<div class="qs-strip-cell">{inner}</div>'


def _system_health_strip() -> str:
    """A single horizontal strip showing the system's running state."""
    cells = []
    # API key
    if providers.has_provider_key():
        cells.append(_strip_cell("API key", "set", _pill("LIVE", "green")))
    else:
        cells.append(_strip_cell("API key", "not set", _pill("DEMO", "amber")))
    # Work folder
    wf = (ss.get("work_folder") or "").strip()
    if wf and Path(wf).exists():
        cells.append(_strip_cell("Work folder", wf, _pill("OK", "green")))
    elif wf:
        cells.append(_strip_cell("Work folder", wf, _pill("missing", "amber")))
    # Learner
    try:
        s = memory.summary_stats()
        n_edits = s["rate_edits"] + s["qty_edits"]
        cells.append(_strip_cell("Learner", f"{n_edits} edits · {s['issued_quotes']} quotes",
                                 _pill("READY", "info") if s["issued_quotes"] else _pill("EMPTY", "grey")))
    except Exception:
        pass
    # Running total
    if ss.line_items:
        cells.append(_strip_cell("Running total", f"R {quote_total(ss.line_items):,.0f}"))
    # Inbox
    try:
        inbox = _list_inbox_files() if (ss.get("work_folder") and Path(ss.get("work_folder")).exists()) else []
        if inbox:
            cells.append(_strip_cell("📥 Inbox", f"{len(inbox)} file(s)", _pill("ready", "info")))
    except Exception:
        pass
    # Active job hint
    h = ss.get("quote_header") or {}
    if h.get("client_name"):
        cells.append(_strip_cell("Job", f"{h.get('client_name')}" + (f" · {h.get('project')}" if h.get("project") else "")))
    return f'<div class="qs-strip">{"".join(cells)}</div>'


def _quote_card(q: dict) -> str:
    """Compact card for a past quote row."""
    title = q.get("quote_name") or q.get("re_subject") or q.get("quote_no") or q["id"]
    sub_bits = []
    if q.get("client_name"): sub_bits.append(f"👤 {q['client_name']}")
    if q.get("quote_no"): sub_bits.append(f"#️ {q['quote_no']}")
    if q.get("parent_quote_id"): sub_bits.append(f"↳ variant of <code>{q['parent_quote_id']}</code>")
    sub = " · ".join(sub_bits) or "—"
    pills = []
    if q.get("labels"):
        for lbl in [l.strip() for l in str(q["labels"]).split(",") if l.strip()][:4]:
            pills.append(_pill(lbl, "info"))
    pill_html = " ".join(pills)
    return (
        f'<div class="qs-card">'
        f'<div class="qs-card-head">'
        f'<span class="qs-card-title">{title}</span>'
        f'<span class="qs-card-meta"><b>R {q["total_zar"]:,.2f}</b></span>'
        f'</div>'
        f'<div class="qs-card-meta">{sub} {pill_html}</div>'
        f'<div class="qs-card-foot">Issued {q["issued_at"]} · ID <code>{q["id"]}</code></div>'
        f'</div>'
    )


def _safe_filename(s: str, default: str = "quote") -> str:
    keep = "-_.()abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
    cleaned = "".join(c if c in keep else "_" for c in (s or "")).strip()
    return (cleaned or default)[:80]


def _to_iso_date(s: str) -> str:
    """Parse common date strings into YYYY-MM-DD. Returns '' on failure.
    Handles: '2026-05-07', '7 May 2026', '7th May 2026', '3rd April 2025'."""
    if not s:
        return ""
    s = s.strip()
    from datetime import datetime
    import re as _re
    # Strip ordinal suffixes (1st, 2nd, 3rd, 4th-31st)
    cleaned = _re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=_re.IGNORECASE)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    return ""


def _today_iso() -> str:
    from datetime import datetime
    return datetime.utcnow().strftime("%Y-%m-%d")


def _quote_filename_base(quote_payload: dict) -> str:
    """Build a human-readable basename: '{Quote No.} — {ISO date} — {scope}'.

    Examples:
      'NPQ 7173 — 2025-04-03 — Proposed new dry wall to Building 1 MBP'
      'NPQ-2026-WS17-001 — 2026-05-07 — Free issue install of acoustic partition'
    """
    header = quote_payload.get("header") or {}
    qno = _safe_filename(header.get("quote_no") or quote_payload.get("memory_id") or "quote")
    iso_date = _to_iso_date(header.get("quote_date") or "") or _today_iso()
    scope_raw = (header.get("re_subject") or header.get("quote_name") or "scope").strip()
    scope = _safe_filename(scope_raw, "scope")[:60].rstrip(" -—_.")
    return f"{qno} — {iso_date} — {scope}"


def _record_learning_from_quote(quote_payload: dict) -> None:
    """Save the client info + every line item into the learning catalog."""
    header = quote_payload.get("header") or {}
    if header.get("client_name"):
        memory.upsert_client(
            name=header.get("client_name") or "",
            vat_reg=header.get("client_vat_reg") or "",
            address=header.get("client_address") or "",
            attention=header.get("attention") or "",
            contact="",
            notes="",
        )
    for li in quote_payload.get("items", []):
        try:
            memory.upsert_learned_item(
                description=li.get("description") or "",
                trade=li.get("trade") or "other",
                unit=li.get("unit") or "no",
                rate=float(li.get("rate_zar") or 0.0),
                subcategory="",
            )
        except Exception:
            continue


def _migrate_old_layout(work_folder: str, dry_run: bool = True) -> dict:
    """Walk old `projects/{P}/quotes/{Q}/*.{pdf,xlsx,json}` and re-organise into
    `clients/{C}/{P}/{Quote No.} — {date} — {scope}.{ext}`.

    For each quote, reads its .json file to get authoritative client/project/scope
    (since folder names can be stale or generic). Returns a report dict.
    """
    folder = Path(work_folder)
    old_root = folder / "projects"
    new_root = folder / "clients"
    if not old_root.exists():
        return {"old_root_exists": False, "moved": 0, "skipped": 0, "errors": []}

    moved: list[tuple[str, str]] = []
    skipped: list[str] = []
    errors: list[str] = []

    for quote_dir in old_root.glob("*/quotes/*/"):
        try:
            json_files = list(quote_dir.glob("*.json"))
            if not json_files:
                skipped.append(f"no .json in {quote_dir}")
                continue
            payload = json.loads(json_files[0].read_text(encoding="utf-8"))
            header = payload.get("header") or {}
            client = _safe_filename(header.get("client_name") or "_unfiled", "_unfiled")
            project = _safe_filename(header.get("project") or quote_dir.parent.parent.name or "_unfiled", "_unfiled")
            target_dir = new_root / client / project
            base = _quote_filename_base(payload)

            for ext in ("pdf", "xlsx", "json"):
                src_candidates = list(quote_dir.glob(f"*.{ext}"))
                if not src_candidates:
                    continue
                src = src_candidates[0]
                dst = target_dir / f"{base}.{ext}"
                if not dry_run:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        skipped.append(f"target exists: {dst.name}")
                        continue
                    src.replace(dst)  # atomic move on same filesystem
                moved.append((str(src), str(dst)))
        except Exception as e:
            errors.append(f"{quote_dir}: {e}")

    # Clean up empty old subfolders (best-effort, only if not dry-run)
    if not dry_run:
        for d in sorted(old_root.glob("*/quotes/*/"), reverse=True):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                pass
        for d in sorted(old_root.glob("*/quotes/"), reverse=True):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                pass
        for d in sorted(old_root.glob("*/"), reverse=True):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                pass

    return {
        "old_root_exists": True,
        "dry_run": dry_run,
        "moved": len(moved),
        "skipped": len(skipped),
        "errors": errors,
        "examples": [(Path(s).name, Path(d).name) for s, d in moved[:5]],
    }


def _autosave_to_work_folder(quote_payload: dict) -> Optional[str]:
    """Save issued PDF + Excel + JSON under:
        {work_folder}/clients/{Client}/{Project}/{Quote No.} — {date} — {scope}.{ext}

    Hierarchy is CLIENT → PROJECT → quote files. A client has many projects,
    each project has many quotes. No per-quote subfolder — files sit flat in
    the project folder so a single project's quotes are scannable at a glance.

    Filename leads with quote no., then ISO date (sortable), then short scope
    summary so you know what each file IS without opening.
    """
    folder = (ss.get("work_folder") or "").strip()
    if not folder:
        return None
    try:
        from excel import issued_quote_to_xlsx
        from pdf_render import render_quote_pdf

        header = quote_payload.get("header") or {}
        client = _safe_filename(header.get("client_name") or "_unfiled", "_unfiled")
        project = _safe_filename(header.get("project") or "_unfiled", "_unfiled")
        target_dir = Path(folder) / "clients" / client / project
        target_dir.mkdir(parents=True, exist_ok=True)

        base = _quote_filename_base(quote_payload)
        # Append (v2), (v3) … if the same base already exists
        candidate = base
        n = 1
        while (target_dir / f"{candidate}.pdf").exists():
            n += 1
            candidate = f"{base} (v{n})"
        base = candidate

        (target_dir / f"{base}.pdf").write_bytes(render_quote_pdf(quote_payload))
        (target_dir / f"{base}.xlsx").write_bytes(issued_quote_to_xlsx(quote_payload))
        (target_dir / f"{base}.json").write_text(
            json.dumps(quote_payload, indent=2, default=str), encoding="utf-8"
        )
        ss["last_saved_dir"] = str(target_dir)
        ss["last_saved_base"] = base
        return str(target_dir)
    except Exception as e:
        ss["last_saved_dir"] = None
        ss["last_saved_error"] = str(e)
        return None


def _inbox_dir() -> Path:
    return Path(ss.get("work_folder") or "").joinpath("inbox") if ss.get("work_folder") else Path()


def _list_inbox_files() -> list[Path]:
    box = _inbox_dir()
    if not box.exists():
        return []
    out: list[Path] = []
    for p in sorted(box.iterdir()):
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".xlsx"}:
            out.append(p)
    return out


def _ingest_result(result, demo: bool, sources: list[str]):
    """Push extraction result into pending review with validators + learner annotations.
    Also auto-fills the per-job header fields (RE: subject, quote name) from the AI's
    suggestion when those fields are empty."""
    new_items = line_items_from_extraction(result)
    validators.annotate_items(new_items)
    annotated = learner.apply_predictions(new_items)
    for li, hints in annotated:
        ss.ai_baseline[li.id] = {"qty": li.quantity, "rate": li.rate_zar}
        if hints:
            ss.learner_hints[li.id] = hints
    ss.pending_items.extend(new_items)

    # Auto-fill per-job header fields if the user hasn't typed anything yet
    h = ss.quote_header
    suggested_subject = getattr(result, "suggested_subject", None)
    suggested_name = getattr(result, "suggested_quote_name", None)
    auto_filled = []
    if suggested_subject and not (h.get("re_subject") or "").strip():
        h["re_subject"] = suggested_subject
        auto_filled.append(f"RE: {suggested_subject}")
    if suggested_name and not (h.get("quote_name") or "").strip():
        h["quote_name"] = suggested_name
        auto_filled.append(f"Quote name: {suggested_name}")
    # Auto-generate quote_no if blank — date-based fallback
    if not (h.get("quote_no") or "").strip():
        from datetime import datetime
        h["quote_no"] = "Q-" + datetime.utcnow().strftime("%Y%m%d-%H%M")
        auto_filled.append(f"Quote no.: {h['quote_no']}")
    if not (h.get("quote_date") or "").strip():
        from datetime import datetime
        now = datetime.utcnow()
        h["quote_date"] = f"{now.day} {now.strftime('%B %Y')}"
        auto_filled.append(f"Date: {h['quote_date']}")
    ss.quote_header = h

    log("extraction_run", details={
        "sources": sources,
        "demo_mode": demo,
        "items_pending_review": len(new_items),
        "auto_filled": auto_filled,
    })
    tag = " — 🧪 demo data" if demo else ""
    msg = f"AI returned {len(new_items)} item(s){tag}"
    if auto_filled:
        msg += " · header auto-filled: " + ", ".join(auto_filled)
    st.success(msg + " — review below before applying.")


def _run_unified_extraction(extra_clarification: str | None = None):
    """Call extract_unified using inputs stashed in session state. If the AI returns a
    ClarificationRequest, stash it so the UI can display the question card."""
    from extract import extract_unified
    from schema import ClarificationRequest, ExtractionResult

    inputs = ss.get("unified_inputs") or []
    if not inputs:
        st.warning("No inputs to process.")
        return

    base_context = ss.get("unified_context") or ""
    if extra_clarification:
        base_context = (base_context + "\n\n" if base_context else "") + f"User clarification: {extra_clarification}"

    if not providers.has_provider_key():
        b, m, fn = inputs[0]
        is_pdf = m == "application/pdf" or fn.lower().endswith(".pdf")
        if is_pdf:
            result = demo_extractor.synthesise_pdf_extraction(fn, n_pages=1, extra_context=base_context)
        else:
            result = demo_extractor.synthesise_extraction(fn, extra_context=base_context)
        _ingest_result(result, demo=True, sources=[fn for _, _, fn in inputs])
        st.rerun()
        return

    # Live progress panel — shows each phase the system is in (Ruflo-style status cards)
    with st.status(f"🤖 Working through {len(inputs)} input file(s)…", expanded=True) as status:
        status.write(f"📁 **Stage 1 — Reading inputs:** {len(inputs)} file(s) queued")
        for _, _, fn in inputs:
            status.write(f"  · `{fn}`")

        status.write("")
        status.write("🖼 **Stage 2 — Image normalisation** (resize to Claude's vision-optimal range, byte-cap < 4 MB each)")

        status.write("")
        status.write("🧠 **Stage 3 — Asking Claude Sonnet 4.5** (vision + rate catalogue + SA building codes + your context)")
        status.write("  *Model is reading dimensions, identifying scope, picking rates from catalogue or proposing market rates…*")

        try:
            outcome = extract_unified(inputs, extra_context=base_context or None)
        except Exception as e:
            status.update(label=f"❌ Extraction failed: {e}", state="error")
            st.error(f"Extraction failed: {e}")
            return

        if isinstance(outcome, ClarificationRequest):
            status.write("")
            status.write(f"❓ **Claude needs guidance:** {outcome.question}")
            status.update(label="🤔 AI needs your guidance — see card below", state="complete", expanded=False)
            ss.clarification = outcome.model_dump()
            ss.clarification["clarification_seq"] = ss.get("clarification_seq", 0) + 1
            log("clarification_requested", details={"q": outcome.question})
            st.rerun()
            return

        if isinstance(outcome, ExtractionResult):
            n = len(outcome.items)
            status.write(f"  ✓ Returned **{n} line item(s)**")
            if outcome.suggested_subject:
                status.write(f"  ✓ Suggested RE: *{outcome.suggested_subject}*")

            status.write("")
            status.write("✅ **Stage 4 — Validators** (sanity ranges per trade, high-value flagging)")

            status.write("")
            status.write("📈 **Stage 5 — Learner** (apply your past edit medians, surface anomalies)")

            status.write("")
            status.write("📝 **Stage 6 — Auto-fill header** (RE: subject, quote name, date if blank)")

            ss.clarification = None
            _ingest_result(outcome, demo=False, sources=[fn for _, _, fn in inputs])
            status.update(label=f"✓ Done — {n} item(s) ready for review", state="complete", expanded=False)
            st.rerun()


# ---------- header ----------

DEMO_MODE = not providers.has_provider_key()

if DEMO_MODE:
    _active = providers.active_provider()
    _label = {"anthropic": "Anthropic", "grok": "xAI Grok", "groq": "Groq"}.get(_active, _active)
    st.warning(
        f"🧪  **DEMO MODE** — no {_label} API key set, so extractions return deterministic synthetic data marked `[DEMO]`. "
        "Every other feature works (review, edit, learner, locks, Excel export). Add a key in the sidebar to enable real vision extraction."
    )

# Anchor for scroll-to-top floating link
st.markdown('<div id="qs-top"></div>', unsafe_allow_html=True)

# Compact app bar — replaces the old big hero. One row: brand · running total.
# Stats (learner / flagged rates) move into the sidebar (less prime real estate).
stats = memory.summary_stats()
learned = stats["rate_edits"] + stats["qty_edits"]
queue = rate_review.review_queue()
running = quote_total(ss.line_items) if ss.line_items else 0

bar_total_html = (
    f'<span class="qs-strip-label">Running total</span> '
    f'<span class="qs-strip-value" style="color:#FFFFFF; font-size:1.1rem;">'
    f'{"R " + format(running, ",.0f") if running else "—"}'
    f"</span>"
)
provider_chip = providers.active_provider()
provider_chip_html = f'<span class="qs-pill qs-pill-brand" style="background:rgba(255,255,255,0.18); color:#fff;">{provider_chip}</span>'

st.markdown(
    f"""
    <div style="
        display:flex; align-items:center; gap:14px;
        padding:12px 22px;
        margin-bottom:14px;
        border-radius:14px;
        background: linear-gradient(135deg, #1E1B4B 0%, #4F46E5 60%, #6D28D9 100%);
        color:#fff;
        box-shadow: 0 4px 16px rgba(79,70,229,0.30);
    ">
      <div style="display:flex; align-items:center; gap:10px; flex:1; min-width:0;">
        {ic("ruler", size=22, color="#FFFFFF")}
        <span style="font-weight:700; font-size:1.1rem; letter-spacing:-0.01em;">QS Live · Quotation Studio</span>
        {provider_chip_html}
      </div>
      <div style="text-align:right;">{bar_total_html}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------- sidebar: undo + zone locks ----------

with st.sidebar:
    st.subheader("LLM provider")
    current_provider = providers.active_provider()
    PROVIDER_LABELS = {
        "ollama":    "Ollama (local Llama 3.2 Vision) — free, on this machine",
        "gemini":    "Google Gemini 2.5 Flash — free, ~1500 req/day, top quality",
        "groq":      "Groq cloud (Llama 3.2 90B Vision) — free tier, fast",
        "anthropic": "Anthropic (Claude Sonnet 4.5) — paid, premium",
        "grok":      "xAI Grok (grok-2-vision) — paid",
    }
    options = list(PROVIDER_LABELS.keys())
    provider_choice = st.radio(
        "Provider",
        options=options,
        index=options.index(current_provider),
        format_func=lambda p: PROVIDER_LABELS[p],
        horizontal=False,
        label_visibility="collapsed",
        key="provider-radio",
    )
    if provider_choice != current_provider:
        key_manager.save_provider_choice(provider_choice)
        log("provider_changed", details={"from": current_provider, "to": provider_choice})
        st.rerun()
    current_provider = provider_choice

    # Per-provider key block (or "no key needed" for ollama)
    if current_provider == "ollama":
        st.success("✓ No API key needed — Ollama runs on this machine. "
                   "Make sure `ollama serve` is running and the vision model is pulled "
                   "(`ollama pull llama3.2-vision:11b`).")
        ss._site_authed = True  # placeholder, gate handled separately
        st.divider()
        st.subheader("Work folder")
        # fall through to next sidebar block via the divider below
        key_label = key_help = key_prefix = None
    elif current_provider == "anthropic":
        key_label = "Anthropic API key"
        key_help = "Get one at console.anthropic.com → API keys. Starts with sk-ant-…"
        key_prefix = "sk-ant-"
    elif current_provider == "grok":
        key_label = "xAI (Grok) API key"
        key_help = "Get one at console.x.ai → API keys. Starts with xai-…"
        key_prefix = "xai-"
    elif current_provider == "gemini":
        key_label = "Google Gemini API key"
        key_help = "Get one at aistudio.google.com → Get API Key. Starts with AIza…"
        key_prefix = "AIza"
    else:  # groq
        key_label = "Groq API key"
        key_help = "Get one at console.groq.com/keys (free tier). Starts with gsk_…"
        key_prefix = "gsk_"

    # Ollama needs no key — skip the entire key-management block
    if key_label is not None:
        st.markdown(f"**{key_label}**")
        if key_manager.has_api_key(current_provider):
            masked = key_manager.get_api_key(current_provider)
            st.success(f"✓ Key set ({masked[:8]}…{masked[-4:]}, {len(masked)} chars)")
            if st.button("Change / clear key", icon=":material/key:", use_container_width=True, key=f"chg-{current_provider}"):
                ss.show_key_input = True
                ss.key_input_seq += 1
                st.rerun()
        else:
            st.info(f"Paste your {current_provider} key below. Saved to qs-app/.env so you only do this once.")
            ss.show_key_input = True

    if key_label is not None and ss.get("show_key_input"):
        widget_key = f"key-input-{current_provider}-{ss.key_input_seq}"
        typed = st.text_input(
            f"{key_label} — paste, verify, then click Save",
            key=widget_key,
            placeholder="",
            help=key_help,
        )
        stripped = (typed or "").strip()
        if stripped:
            preview = f"{stripped[:8]}…{stripped[-4:]}" if len(stripped) > 12 else stripped
            if stripped.startswith(key_prefix):
                st.caption(f"✓ Looks valid · {len(stripped)} chars · {preview}")
            else:
                st.caption(f"⚠ Doesn't start with `{key_prefix}` (got `{preview}`, {len(stripped)} chars). Save anyway?")
        else:
            st.caption("👆 Paste your key into the field above.")

        col_save, col_clear = st.columns(2)
        save_clicked = col_save.button("Save", icon=":material/save:", type="primary", use_container_width=True, key=f"save-{current_provider}-{ss.key_input_seq}")
        clear_clicked = col_clear.button("Clear stored key", icon=":material/close:", use_container_width=True, key=f"clear-{current_provider}-{ss.key_input_seq}")

        if save_clicked:
            if not stripped:
                st.error("The field is empty. Paste your key first, then click Save.")
            else:
                key_manager.save_api_key(stripped, current_provider)
                ss.show_key_input = False
                ss.key_input_seq += 1
                log("save_api_key", details={"provider": current_provider, "length": len(stripped)})
                st.toast(f"✓ {current_provider} key saved", icon="✅")
                st.rerun()
        if clear_clicked:
            key_manager.clear_api_key(current_provider)
            ss.show_key_input = True
            ss.key_input_seq += 1
            log("clear_api_key", details={"provider": current_provider})
            st.rerun()

    # ---------- Diagnostic: which secrets actually loaded ----------
    with st.expander("⚙️ Secrets diagnostic", expanded=False):
        diag_rows = []
        secrets_to_check = [
            "ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY",
            "EXTRACTION_PROVIDER", "SITE_PASSWORD", "OLLAMA_URL",
        ]
        for name in secrets_to_check:
            val_env = os.environ.get(name, "")
            val_secret = ""
            try:
                val_secret = str(st.secrets.get(name, ""))
            except Exception:
                val_secret = ""
            if val_env:
                origin, val = "env", val_env
            elif val_secret:
                origin, val = "st.secrets", val_secret
            else:
                origin, val = "—", ""
            if val and name in ("EXTRACTION_PROVIDER", "OLLAMA_URL"):
                shown = val
            elif val and len(val) > 12:
                shown = f"{val[:6]}…{val[-4:]}  ({len(val)} chars)"
            elif val:
                shown = f"({len(val)} chars)"
            else:
                shown = "(not set)"
            diag_rows.append({"Secret": name, "Origin": origin, "Value": shown})
        st.dataframe(diag_rows, hide_index=True, use_container_width=True)
        st.caption(
            "Origin shows where the value was read from. If a secret is `(not set)` "
            "but you expected it, check Streamlit Cloud → Settings → Secrets, then "
            "wait 30s and refresh."
        )

    st.divider()
    st.subheader("Work folder")
    new_folder = st.text_input(
        "Auto-save issued quotes to:",
        value=ss.work_folder,
        key="work-folder-input",
        help=r"Local path. Quotes save under {folder}\quotes\{quote_no}\. Default: E:\NdlovuQS",
    )
    if new_folder != ss.work_folder:
        ss.work_folder = new_folder
        _save_work_folder(new_folder)
    folder_exists = Path(ss.work_folder).exists() if ss.work_folder else False
    st.caption(f"{'✓ Folder reachable' if folder_exists else '⚠ Folder not yet present (will be created on first save)'}")

    st.divider()
    st.subheader("Job")
    if st.button("New job", icon=":material/restart_alt:", use_container_width=True,
                 help="Clears client, quote no., RE: subject, line items, and pending review. Keeps your company info, banking, payment terms, and learner memory."):
        # Reset per-job header fields
        h = ss.quote_header
        for f in QuoteHeader.per_job_fields():
            if f in h:
                h[f] = "" if isinstance(h.get(f), str) else h.get(f)
        ss.quote_header = h
        # Clear all Quote-header widget session-state keys so the next NPQ auto-suggest takes effect
        for k in list(ss.keys()):
            if k.startswith("hd-"):
                try:
                    del ss[k]
                except Exception:
                    pass
        # Clear line items and pending
        ss.line_items = []
        ss.pending_items = []
        ss.frozen_quote = None
        ss.uploads = {}
        ss.learner_hints = {}
        ss.ai_baseline = {}
        ss.history = []
        ss.unified_inputs = []
        ss.unified_context = ""
        ss.clarification = None
        log("new_job")
        st.toast("Started a new job — client + scope cleared.", icon="🆕")
        st.rerun()

    st.divider()
    st.subheader("Controls")
    if versioning.can_undo(ss.history):
        last = versioning.last_label(ss.history)
        if st.button(f"Undo: {last}", icon=":material/undo:", use_container_width=True):
            restored, label = versioning.undo(ss.history)
            if restored is not None:
                ss.line_items = restored
                log("undo", details={"reverted": label})
                st.rerun()
    else:
        st.caption("No undo history yet.")

    st.divider()
    st.subheader("Zones")
    if ss.line_items:
        zones_present = sorted({li.zone for li in ss.line_items})
        for z in zones_present:
            locked = z in ss.locked_zones
            label = f"🔒 {z}" if locked else f"🔓 {z}"
            if st.button(label, key=f"lock-{z}", use_container_width=True):
                if locked:
                    ss.locked_zones.discard(z)
                    log("unlock_zone", details={"zone": z})
                else:
                    ss.locked_zones.add(z)
                    log("lock_zone", details={"zone": z})
                st.rerun()
        st.caption("Click a zone to toggle lock. Locked zones reject new extractions.")
    else:
        st.caption("Zones will appear here once you have line items.")

# ---------- tabs ----------

# Live system-health strip — visible at all times so the operator knows the state
st.markdown(_system_health_strip(), unsafe_allow_html=True)

tab_quote, tab_past, tab_invoices, tab_admin, tab_rates, tab_audit = st.tabs(
    [
        ":material/architecture: Quote builder",
        ":material/folder: Past quotes",
        ":material/request_quote: Invoices",
        ":material/contacts: Clients & Projects",
        ":material/payments: Rate review queue",
        ":material/receipt_long: Audit log",
    ]
)

# ============================================================================
# TAB 1 — QUOTE BUILDER
# ============================================================================

with tab_quote:

    # ===== PAGE HEADER (Xero / Zoho / Sage style) =====
    h = ss.quote_header
    if not (h.get("quote_no") or "").strip():
        try:
            h["quote_no"] = memory.suggest_next_quote_no("NPQ")
            ss.quote_header = h
        except Exception:
            pass
    qno = (h.get("quote_no") or "—").strip() or "—"
    client = (h.get("client_name") or "").strip()
    project = (h.get("project") or "").strip()
    sow = (h.get("re_subject") or "").strip()

    # Status pill — Xero/Sage convention: Draft is neutral, amber reserved for actual problems
    if ss.frozen_quote is not None:
        status_label, status_class = "Issued", "qs-pill-green"
    elif ss.line_items:
        status_label, status_class = "Draft", "qs-pill-grey"
    elif ss.pending_items:
        status_label, status_class = "Reviewing", "qs-pill-info"
    else:
        status_label, status_class = "New", "qs-pill-grey"

    # Subtitle: client · project · scope (omit empties; HTML-escape free-text)
    import html as _html
    sub_bits = []
    sub_bits.append(_html.escape(client) if client else '<span style="color:#B91C1C">no client</span>')
    if project:
        sub_bits.append(_html.escape(project))
    elif client:
        sub_bits.append('<span style="color:#B91C1C">no project</span>')
    subtitle_html = " · ".join(sub_bits)
    if sow:
        subtitle_html += f' &nbsp;—&nbsp; <span style="font-style:italic">{_html.escape(sow)}</span>'

    st.markdown(
        f'''<div class="qs-page-header">
              <div class="qs-page-header__title">
                <div class="qs-page-header__eyebrow">QUOTATION</div>
                <h1 class="qs-page-header__h1">{qno}</h1>
                <div class="qs-page-header__subtitle">{subtitle_html}</div>
              </div>
              <div class="qs-page-header__meta">
                <span class="qs-pill {status_class}">{status_label}</span>
              </div>
            </div>''',
        unsafe_allow_html=True,
    )

    # ----- Quote header (editable cover-page fields) -----
    with st.expander("Quote header (editable — company, client, quote no, terms)",
                       expanded=True, icon=":material/edit_note:"):
        h = ss.quote_header

        # ===== REQUIRED: Client + Project, dropdown + inline-add =====
        try:
            saved_clients = memory.list_clients() or []
        except Exception:
            saved_clients = []
        saved_clients = [c for c in saved_clients if c and c.get("name")]
        client_names = sorted({c["name"] for c in saved_clients})
        try:
            saved_projects_all = memory.list_projects_admin() or []
        except Exception:
            saved_projects_all = []
        saved_projects_all = [p for p in saved_projects_all if p and p.get("name")]

        ADD_NEW = "+ Add new…"
        NONE_SEL = "— select —"

        rcol_client, rcol_project = st.columns(2)

        # ----- Client dropdown -----
        with rcol_client:
            options = [NONE_SEL] + client_names + [ADD_NEW]
            current = h.get("client_name") or ""
            try:
                idx = options.index(current) if current in options else 0
            except ValueError:
                idx = 0
            client_pick = st.selectbox(
                "Client *",
                options=options,
                index=idx,
                key="hd-client-select",
                help="Required. Pick from existing clients or add a new one.",
            )
            if client_pick == ADD_NEW:
                with st.container(border=True):
                    st.caption("New client")
                    n1 = st.text_input("Name *", key="hd-newclient-name")
                    n_vat = st.text_input("VAT reg.", key="hd-newclient-vat")
                    n_addr = st.text_input("Site / address", key="hd-newclient-addr")
                    n_attn = st.text_input("Attention", key="hd-newclient-attn")
                    if st.button("Save & use", icon=":material/save:", key="hd-newclient-save", type="primary", use_container_width=True):
                        if not n1.strip():
                            st.error("Client name is required.")
                        else:
                            memory.upsert_client(n1, n_vat, n_addr, n_attn, "", "")
                            h["client_name"] = n1.strip()
                            h["client_vat_reg"] = n_vat
                            h["client_address"] = n_addr
                            h["attention"] = n_attn
                            ss.quote_header = h
                            log("admin_add_client", details={"name": n1, "via": "header"})
                            st.toast(f"Saved client {n1.strip()}", icon="✅")
                            st.rerun()
            elif client_pick != NONE_SEL:
                # Pull canonical fields from the saved record
                src = next((c for c in saved_clients if c.get("name") == client_pick), None)
                if src and h.get("client_name") != client_pick:
                    h["client_name"] = src.get("name") or ""
                    h["client_vat_reg"] = src.get("vat_reg") or ""
                    h["client_address"] = src.get("address") or ""
                    h["attention"] = src.get("attention") or ""
                    ss.quote_header = h

        # ----- Project dropdown (filter to selected client where possible) -----
        with rcol_project:
            selected_client = h.get("client_name") or ""
            # Prefer projects whose primary_client matches; fall back to all
            if selected_client:
                project_for_client = [p for p in saved_projects_all
                                       if (p.get("primary_client") or "").strip().lower() == selected_client.strip().lower()]
            else:
                project_for_client = []
            project_names = sorted({p["name"] for p in project_for_client})
            other_projects = sorted({p["name"] for p in saved_projects_all if p["name"] not in project_names})

            options = [NONE_SEL] + project_names
            if other_projects:
                options += [f"— other projects ({len(other_projects)}) —"] + other_projects
            options += [ADD_NEW]

            current_proj = h.get("project") or ""
            try:
                p_idx = options.index(current_proj) if current_proj in options else 0
            except ValueError:
                p_idx = 0
            project_pick = st.selectbox(
                "Project *",
                options=options,
                index=p_idx,
                key="hd-project-select",
                help="Required. Pick from existing projects or add a new one.",
            )
            if project_pick == ADD_NEW:
                with st.container(border=True):
                    st.caption("New project")
                    pn = st.text_input("Project name *", key="hd-newproject-name")
                    pc = st.text_input("Primary client", value=selected_client, key="hd-newproject-client")
                    p_notes = st.text_input("Notes", key="hd-newproject-notes")
                    if st.button("Save & use", icon=":material/save:", key="hd-newproject-save", type="primary", use_container_width=True):
                        if not pn.strip():
                            st.error("Project name is required.")
                        else:
                            memory.upsert_project_admin(pn, pc, p_notes, "active")
                            h["project"] = pn.strip()
                            ss.quote_header = h
                            log("admin_add_project", details={"name": pn, "via": "header"})
                            st.toast(f"Saved project {pn.strip()}", icon="✅")
                            st.rerun()
            elif project_pick != NONE_SEL and not project_pick.startswith("— other projects"):
                if h.get("project") != project_pick:
                    h["project"] = project_pick
                    ss.quote_header = h

        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Your company**")
            h["company_name"] = st.text_input("Company name", value=h.get("company_name", ""), key="hd-co-name")
            h["company_vat_reg"] = st.text_input("Company VAT reg", value=h.get("company_vat_reg", ""), key="hd-co-vat")
            h["company_address"] = st.text_input("Company address", value=h.get("company_address", ""), key="hd-co-addr")
            h["company_contact"] = st.text_input("Company contact (phone / email)", value=h.get("company_contact", ""), key="hd-co-contact")
        with cols[1]:
            st.markdown("**Client details** *(auto-filled from dropdown above; editable)*")
            h["client_vat_reg"] = st.text_input("VAT reg", value=h.get("client_vat_reg", ""), key="hd-cl-vat")
            h["client_address"] = st.text_input("Site / address", value=h.get("client_address", ""), key="hd-cl-addr")
            h["attention"] = st.text_input("ATTENTION:", value=h.get("attention", ""), key="hd-att")

        # Auto-suggest a Quote No. when blank (NPQ + next sequence based on past issues)
        if not (h.get("quote_no") or "").strip():
            try:
                h["quote_no"] = memory.suggest_next_quote_no("NPQ")
            except Exception:
                pass

        cols = st.columns(4)
        with cols[0]:
            h["quote_no"] = st.text_input("Quote No.", value=h.get("quote_no", ""), key="hd-qno",
                                          help="Auto-suggested as 'NPQ {next sequence}'; override if needed")
        with cols[1]:
            h["quote_date"] = st.text_input("Issue date", value=h.get("quote_date", ""), key="hd-date")
        with cols[2]:
            h["expiry_date"] = st.text_input("Valid until", value=h.get("expiry_date", ""), key="hd-expiry")
        with cols[3]:
            h["project_reference"] = st.text_input("Project ref.", value=h.get("project_reference", ""), key="hd-projref")

        h["re_subject"] = st.text_input("RE: (subject line)", value=h.get("re_subject", ""), key="hd-re")

        # Internal naming + labels (project itself is the required dropdown above)
        cols = st.columns(2)
        with cols[0]:
            h["quote_name"] = st.text_input("Quote name (internal)", value=h.get("quote_name", ""), key="hd-qname",
                                            help="Short internal label, e.g. 'Pool refurb v2'")
        with cols[1]:
            h["labels"] = st.text_input("Labels (comma-separated)", value=h.get("labels", ""), key="hd-labels",
                                        help="e.g. urgent, building1, refit")

        h["payment_terms"] = st.text_area("Payment terms (one per line, all bold on the doc)",
                                          value=h.get("payment_terms", ""), height=80, key="hd-terms")
        # Banking details + acceptance block are not part of your ATESS template,
        # so they're not exposed here. They're still in the schema if you ever
        # want them on a future template.

        cols = st.columns([1, 1, 4])
        with cols[0]:
            h["show_vat"] = st.checkbox("Show VAT on quote", value=h.get("show_vat", False), key="hd-show-vat")
        with cols[1]:
            h["vat_pct"] = st.number_input("VAT %", value=float(h.get("vat_pct", 15.0)), step=0.5, key="hd-vat-pct")

        ss.quote_header = h


    # ----- STEP 2: SITE SURVEY -----
    # ----- Site Survey (foreman template upload) -----
    with st.expander("Site Survey — download blank template / import filled-in survey",
                       expanded=False, icon=":material/content_paste:"):
        col_dl, col_info = st.columns([1, 3])
        with col_dl:
            st.download_button(
                "⬇️ Download blank template",
                data=survey_template.generate_template_xlsx(),
                file_name="site-survey-template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with col_info:
            st.caption(
                "Send `site-survey-template.xlsx` to your foreman. They fill rows on site (zone, description, qty, unit, photo refs, notes), "
                "save with photos in the same folder, and send back. Then upload the filled xlsx + photos below."
            )
        st.divider()

        survey_xlsx = st.file_uploader(
            "Filled site survey (.xlsx)",
            type=["xlsx"],
            accept_multiple_files=False,
            key="survey-xlsx",
        )
        survey_photos = st.file_uploader(
            "Photos referenced by the survey (any/all photos in the job folder)",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="survey-photos",
        )
        run_survey = st.button(
            "📋 Process site survey",
            type="primary",
            disabled=not survey_xlsx or ss.frozen_quote is not None,
            use_container_width=True,
        )

        if run_survey and survey_xlsx:
            try:
                data = survey_template.parse_survey_xlsx(survey_xlsx.getvalue())
            except Exception as e:
                st.error(f"Couldn't parse the survey: {e}")
                data = None

            if data is not None:
                if not data.items:
                    st.warning("No items found in the survey. Make sure the foreman filled in the rows below 'Zone / Area'.")
                else:
                    st.info(f"Parsed {len(data.items)} item(s) from survey · {len(data.referenced_photos())} photo(s) referenced.")

                    # Pre-fill the quote header from the survey
                    h = ss.quote_header
                    if data.header.client and not h.get("client_name"):
                        h["client_name"] = data.header.client
                    if data.header.site and not h.get("client_address"):
                        h["client_address"] = data.header.site
                    if data.header.job_ref and not h.get("quote_no"):
                        h["quote_no"] = data.header.job_ref
                    if data.header.date and not h.get("quote_date"):
                        h["quote_date"] = data.header.date
                    if data.header.scope and not h.get("re_subject"):
                        h["re_subject"] = data.header.scope
                    ss.quote_header = h

                    # Build the AI input: photos go as image blocks, survey text goes as context
                    photo_inputs: list[tuple[bytes, str, str]] = []
                    referenced = {p.lower() for p in data.referenced_photos()}
                    used_photos = []
                    if survey_photos:
                        for ph in survey_photos:
                            # If the survey explicitly references this photo OR there's no reference list,
                            # include it. Otherwise skip — keeps the AI focused.
                            include = (
                                not referenced
                                or ph.name.lower() in referenced
                                or ph.name.split('.')[0].lower() in {r.split('.')[0] for r in referenced}
                            )
                            if include:
                                photo_inputs.append((ph.getvalue(), ph.type or "image/jpeg", ph.name))
                                used_photos.append(ph.name)
                                # Stash for the source-files panel
                                if ph.name not in ss.uploads:
                                    ss.uploads[ph.name] = {
                                        "bytes": ph.getvalue(),
                                        "media_type": ph.type or "image/jpeg",
                                        "is_pdf": False,
                                    }

                    if not photo_inputs:
                        # No photos — send a 1×1 placeholder so the API still gets called with text only
                        st.warning("No photos matched the survey references. Continuing with text-only — quantities will be less precise.")

                    # Stash for the unified pipeline + clarification re-runs
                    ss.unified_inputs = photo_inputs
                    ss.unified_context = survey_template.survey_to_extra_context(data)
                    log("survey_imported", details={
                        "items_in_survey": len(data.items),
                        "photos_used": used_photos,
                    })
                    _run_unified_extraction()


# Render the clarification card if the AI is asking for guidance
with tab_quote:
    if ss.get("clarification"):
        clar = ss.clarification
        with st.container(border=True):
            st.markdown(f"### 🤔 The AI needs your guidance")
            st.markdown(f"**{clar['question']}**")
            if clar.get("context_so_far"):
                st.caption(f"What I see: {clar['context_so_far']}")

            # Suggested options as quick-pick buttons
            options = clar.get("options") or []
            if options:
                ocols = st.columns(min(len(options), 5))
                for i, opt in enumerate(options):
                    if ocols[i % len(ocols)].button(opt, key=f"clarify-opt-{ss.clarification['clarification_seq']}-{i}"):
                        ss.clarification = None
                        log("clarification_answered", details={"answer": opt})
                        _run_unified_extraction(extra_clarification=opt)
                        st.rerun()

            # Free-text answer
            free = st.text_input("Or type your own answer:",
                                 key=f"clarify-free-{ss.clarification['clarification_seq']}")
            send_col, cancel_col = st.columns(2)
            if send_col.button("Send answer", type="primary", key=f"clarify-send-{ss.clarification['clarification_seq']}"):
                if free.strip():
                    ss.clarification = None
                    log("clarification_answered", details={"answer": free.strip()})
                    _run_unified_extraction(extra_clarification=free.strip())
                    st.rerun()
                else:
                    st.warning("Type an answer or click a suggested option.")
            if cancel_col.button("Cancel and discard", key=f"clarify-cancel-{ss.clarification['clarification_seq']}"):
                ss.clarification = None
                log("clarification_cancelled")
                st.rerun()


    # ----- STEP 3: DRAWINGS / PHOTOS / VIDEOS -----
    # ----- DOMINANT INPUT ZONE — page's primary action, immediately under header
    st.markdown(
        '<div style="display:flex; align-items:center; justify-content:space-between; '
        'gap:10px; margin: 14px 0 10px 2px;">'
        '<div style="display:flex; align-items:baseline; gap:10px;">'
        '<span style="font-size:0.72rem; font-weight:600; letter-spacing:0.08em; '
        'text-transform:uppercase; color:var(--brand);">START HERE</span>'
        '<span style="font-size:0.92rem; color:var(--ink-2); font-weight:500;">'
        'Drop your drawings — AI takes off the line items</span>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    # Clean dropzone card — flat, hairline border (Linear/Stripe pattern). No gradients.
    with st.container(border=True):
        st.markdown(
            '<div style="display:flex; align-items:center; gap:12px; margin-bottom:6px;">'
            '<div style="width:32px; height:32px; border-radius:6px; '
            'background: var(--brand-soft); display:flex; align-items:center; '
            'justify-content:center;">'
            f'{ic("upload", size=18, color="#5E6AD2")}'
            '</div>'
            '<div>'
            '<div style="font-size:1rem; font-weight:600; color:var(--ink); letter-spacing:-0.01em;">'
            'Drop drawings, photos, PDFs or video</div>'
            '<div style="font-size:0.82rem; color:var(--ink-3); margin-top:1px;">'
            'One file or many. PDFs auto-paginate. Videos are sampled into ~8 keyframes.'
            '</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )
        uploads = st.file_uploader(
            " ",
            type=["png", "jpg", "jpeg", "webp", "pdf", "mp4", "mov", "webm", "m4v"],
            accept_multiple_files=True,
            key="uploader",
            label_visibility="collapsed",
        )
        # ----- Voice → text dictation (iOS Safari, Chrome, Edge supported) -----
        if _stt is not None:
            mic_col, hint_col = st.columns([1, 4])
            with mic_col:
                spoken = _stt(
                    language="en-ZA",
                    start_prompt="🎙 Voice note",
                    stop_prompt="⏹ Stop",
                    just_once=True,
                    use_container_width=True,
                    key=f"ctx-stt-{ss.ctx_seq}",
                )
            with hint_col:
                st.caption(
                    "Tap **Voice note** → speak (room, scope, dimensions). Stops on tap-stop or silence. "
                    "Transcribed text appends to the context box."
                )
            if spoken:
                glue = "\n" if ss.get("ctx_buffer") else ""
                ss.ctx_buffer = (ss.get("ctx_buffer") or "") + glue + spoken.strip()
                ss.ctx_seq += 1  # rotate widget keys so the textarea picks up new initial value
                st.rerun()

        extra_context = st.text_area(
            "Optional context (room, scope, dimensions, what you want the AI to focus on)",
            value=ss.get("ctx_buffer", ""),
            placeholder="e.g. 'Bathroom 1 refit — left photo is existing, right photo is proposed'",
            height=80,
            key=f"unified-context-{ss.ctx_seq}",
        )
        ss.ctx_buffer = extra_context

        # Clipboard paste — captures whatever's on the clipboard (screenshot, copied image, text)
        if paste_image_button is not None:
            paste_cols = st.columns([1, 4])
            with paste_cols[0]:
                paste_result = paste_image_button(
                    label="Paste image",
                    key=f"paste-img-{ss.ctx_seq}",
                    text_color="#0A2540",
                    background_color="#EAF1F8",
                    hover_background_color="#D6DEE3",
                    errors="ignore",
                )
            with paste_cols[1]:
                st.caption(
                    "Copy any image (screenshot, WhatsApp, browser) → click **Paste image** to add it as an input. "
                    "Or paste text directly into the context box above."
                )
            if paste_result and getattr(paste_result, "image_data", None) is not None:
                # Convert PIL Image → PNG bytes, queue alongside other inputs
                import io as _io
                buf = _io.BytesIO()
                paste_result.image_data.save(buf, format="PNG")
                pasted_bytes = buf.getvalue()
                from datetime import datetime as _dt
                stamp = _dt.utcnow().strftime("%Y%m%d-%H%M%S")
                pasted_name = f"pasted-{stamp}.png"
                # Stash into unified_inputs so it goes through the next Run
                inputs_so_far = list(ss.get("unified_inputs") or [])
                inputs_so_far.append((pasted_bytes, "image/png", pasted_name))
                ss.unified_inputs = inputs_so_far
                if pasted_name not in ss.uploads:
                    ss.uploads[pasted_name] = {"bytes": pasted_bytes, "media_type": "image/png", "is_pdf": False}
                ss.ctx_seq += 1
                log("clipboard_paste_image", details={"name": pasted_name, "bytes": len(pasted_bytes)})
                st.toast(f"Pasted image queued: {pasted_name}", icon="📋")
                st.rerun()
        run = st.button(
            "Run extraction", icon=":material/play_arrow:", type="primary",
            disabled=not uploads or ss.frozen_quote is not None,
            use_container_width=True,
        )

        if run and uploads:
            # Stash bytes on session state so we can re-call after a clarification answer.
            stashed = []
            video_frame_total = 0
            for up in uploads:
                is_pdf = (up.type == "application/pdf") or up.name.lower().endswith(".pdf")
                is_video = is_video_filename(up.name) or (up.type or "").startswith("video/")
                raw_bytes = up.getvalue()

                if is_video and extract_video_keyframes is not None:
                    suffix = "." + up.name.lower().rsplit(".", 1)[-1]
                    with st.spinner(f"Sampling keyframes from {up.name}…"):
                        frames = extract_video_keyframes(raw_bytes, n_frames=8, suffix=suffix)
                    if not frames:
                        st.warning(f"Couldn't read frames from {up.name} — install opencv-python-headless or check the format.")
                        continue
                    base = up.name.rsplit(".", 1)[0]
                    for i, (png_bytes, mime, fname) in enumerate(frames):
                        labelled_name = f"{base}__{fname}"
                        stashed.append((png_bytes, mime, labelled_name))
                        if labelled_name not in ss.uploads:
                            ss.uploads[labelled_name] = {"bytes": png_bytes, "media_type": mime, "is_pdf": False}
                    video_frame_total += len(frames)
                    log("video_keyframes_extracted", details={"video": up.name, "frames": len(frames)})
                    continue

                stashed.append((raw_bytes, up.type or ("application/pdf" if is_pdf else "image/jpeg"), up.name))

                # Thumbnail for source-files panel
                if up.name not in ss.uploads:
                    if is_pdf:
                        try:
                            pages = pdf_pages_to_pngs(raw_bytes, scale=1.5)
                            ss.uploads[up.name] = {
                                "bytes": pages[0][1] if pages else b"",
                                "media_type": "image/png",
                                "is_pdf": True,
                                "pdf_page_count": len(pages),
                            }
                        except Exception:
                            ss.uploads[up.name] = {"bytes": b"", "media_type": "application/pdf", "is_pdf": True, "pdf_page_count": 0}
                    else:
                        ss.uploads[up.name] = {"bytes": raw_bytes, "media_type": up.type or "image/jpeg", "is_pdf": False}

            if video_frame_total:
                st.toast(f"Extracted {video_frame_total} keyframe(s) from video", icon="🎬")

            ss.unified_inputs = stashed
            ss.unified_context = extra_context or ""
            _run_unified_extraction()

    # ----- Inbox folder watcher — drop files in E:\NdlovuQS\inbox\ and click Process -----
    inbox_files = _list_inbox_files()
    # Collapsed by default; expand if there are files waiting
    inbox_label = f"Inbox ({len(inbox_files)} file(s) ready)" if inbox_files else "Inbox"
    with st.expander(inbox_label, expanded=bool(inbox_files), icon=":material/inbox:"):
        cols_h = st.columns([3, 1])
        with cols_h[0]:
            st.subheader("📥 Inbox")
            st.caption(
                f"Drop photos/PDFs/surveys into `{_inbox_dir()}` from anywhere — "
                "Explorer, drag-drop, OneDrive sync, WhatsApp save-to-folder. Click **Process inbox** and the AI takes it from there."
            )
        with cols_h[1]:
            try:
                import os
                if st.button("Open inbox folder", use_container_width=True, disabled=not _inbox_dir().exists()):
                    os.startfile(str(_inbox_dir()))
            except Exception:
                pass

        if not inbox_files:
            st.info(f"Inbox empty. Drop files in `{_inbox_dir()}` and refresh.")
        else:
            st.markdown(f"**{len(inbox_files)} file(s) ready to process:**")
            for p in inbox_files:
                size_kb = p.stat().st_size / 1024
                size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
                st.markdown(f"- `{p.name}` ({size_str})")

            cols_b = st.columns([1, 1, 2])
            move_after = cols_b[0].checkbox("Move processed → `inbox/processed/`", value=True, key="inbox-move")
            run_inbox = cols_b[1].button(
                "Process inbox", icon=":material/rocket_launch:", type="primary", use_container_width=True,
                disabled=ss.frozen_quote is not None,
            )
            if run_inbox:
                stashed: list[tuple[bytes, str, str]] = []
                for p in inbox_files:
                    raw = p.read_bytes()
                    suffix = p.suffix.lower()
                    media = "application/pdf" if suffix == ".pdf" else "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "application/octet-stream"
                    if suffix == ".xlsx":
                        # parse as a foreman survey
                        try:
                            data = survey_template.parse_survey_xlsx(raw)
                            ss.unified_context = ((ss.get("unified_context") or "") + "\n\n" + survey_template.survey_to_extra_context(data)).strip()
                            # pre-fill header
                            h = ss.quote_header
                            for src, dst in [
                                ("client", "client_name"), ("site", "client_address"),
                                ("job_ref", "quote_no"), ("date", "quote_date"), ("scope", "re_subject"),
                            ]:
                                v = getattr(data.header, src, "")
                                if v and not h.get(dst):
                                    h[dst] = v
                            ss.quote_header = h
                            log("inbox_xlsx_parsed", details={"file": p.name, "items": len(data.items)})
                            continue
                        except Exception as e:
                            st.warning(f"Couldn't parse {p.name} as survey: {e}")
                            continue
                    stashed.append((raw, media, p.name))
                    if p.name not in ss.uploads:
                        ss.uploads[p.name] = {"bytes": raw if suffix != ".pdf" else b"",
                                              "media_type": media, "is_pdf": suffix == ".pdf"}

                if stashed or ss.get("unified_context"):
                    ss.unified_inputs = (ss.get("unified_inputs") or []) + stashed
                    log("inbox_processed", details={"count": len(inbox_files)})
                    if move_after:
                        proc_dir = _inbox_dir() / "processed"
                        proc_dir.mkdir(exist_ok=True)
                        from datetime import datetime as _dt
                        stamp = _dt.utcnow().strftime("%Y%m%d-%H%M%S")
                        for p in inbox_files:
                            try:
                                p.rename(proc_dir / f"{stamp}_{p.name}")
                            except Exception:
                                pass
                    _run_unified_extraction()

    # ----- Pending review (diff-confirm) -----
    if ss.pending_items:
        st.subheader("⚠ Pending — review before applying")
        st.caption("New extraction results. Untick items you don't want, then click *Apply selected*. Locked zones and likely duplicates are flagged.")

        existing_codes = {li.rate_code for li in ss.line_items if li.rate_code}
        selections: dict[str, bool] = {}

        for pi in ss.pending_items:
            warn_bits: list[str] = []
            zone_locked = pi.zone in ss.locked_zones
            if zone_locked:
                warn_bits.append(f"🔒 Zone `{pi.zone}` is locked — will be skipped.")
            if pi.rate_code and pi.rate_code in existing_codes:
                warn_bits.append(f"⚡ Likely duplicate of existing item with rate `{pi.rate_code}`.")
            for w in pi.sanity_warnings:
                warn_bits.append(w)

            with st.container(border=True):
                cols = st.columns([0.4, 4, 1, 1, 1, 1.5])
                with cols[0]:
                    default = not zone_locked
                    selections[pi.id] = st.checkbox(" ", value=default, key=f"pend-{pi.id}", label_visibility="collapsed")
                with cols[1]:
                    band = pi.confidence_band
                    pill = {"green": "🟢", "amber": "🟡", "red": "🔴"}[band]
                    st.markdown(f"**{pi.description}** · `{pi.zone}`")
                    prov_bits = [f"📷 {pi.provenance.source_image}"]
                    if pi.provenance.evidence:
                        prov_bits.append(pi.provenance.evidence)
                    st.caption(f"{pill} `{pi.confidence:.2f}` · " + " · ".join(prov_bits))
                    if pi.notes:
                        st.caption(f"📝 {pi.notes}")
                    for hint in ss.learner_hints.get(pi.id, []):
                        st.caption(hint)
                    for w in warn_bits:
                        st.caption(w)
                cols[2].markdown(f"{pi.quantity:.2f} {pi.unit}")
                cols[3].markdown(f"`{pi.trade}`")
                cols[4].markdown(f"R {pi.rate_zar:,.2f}")
                cols[5].markdown(f"**R {pi.total_zar:,.2f}**")

        col_apply, col_discard = st.columns([1, 1])
        with col_apply:
            if st.button("Apply selected", icon=":material/check:", type="primary", use_container_width=True):
                take_snapshot("apply pending extraction")
                added = 0
                skipped_locked = 0
                for pi in ss.pending_items:
                    if not selections.get(pi.id, False):
                        continue
                    if pi.zone in ss.locked_zones:
                        skipped_locked += 1
                        continue
                    ss.line_items.append(pi)
                    added += 1
                log("apply_pending", details={"added": added, "skipped_locked": skipped_locked})
                ss.pending_items = []
                st.success(f"Applied {added} item(s)" + (f", skipped {skipped_locked} in locked zones" if skipped_locked else ""))
                st.rerun()
        with col_discard:
            if st.button("Discard pending", icon=":material/close:", use_container_width=True):
                log("discard_pending", details={"count": len(ss.pending_items)})
                ss.pending_items = []
                st.rerun()

    # ----- Source images thumbnails -----
    if ss.uploads:
        with st.expander(f"Source files ({len(ss.uploads)})", expanded=False):
            cols = st.columns(min(4, len(ss.uploads)))
            for i, (fname, meta) in enumerate(ss.uploads.items()):
                with cols[i % len(cols)]:
                    cap = fname
                    if meta.get("is_pdf"):
                        cap = f"📄 {fname} ({meta.get('pdf_page_count', '?')} pages — first shown)"
                    if meta.get("bytes"):
                        st.image(meta["bytes"], caption=cap, use_container_width=True)
                    else:
                        st.caption(cap)

    # ----- Line items review -----
    st.subheader("2. Review line items")

    if not ss.line_items and not ss.pending_items:
        st.info("Upload images above and click *Run extraction* to start a quote.")
    elif ss.line_items:
        # Refresh validator annotations on every render (qty/rate changes during edits)
        validators.annotate_items(ss.line_items)

        # ---- Bulk confirm action bar ----
        pending = [li for li in ss.line_items if li.state in (EditState.AI_SUGGESTED, EditState.USER_EDITED)]
        if pending:
            bar = st.container(border=True)
            cols = bar.columns([3, 1.2, 1.2, 1.2])
            cols[0].markdown(
                f"**{len(pending)} item(s) awaiting confirmation.** "
                "Use bulk actions below to skip clicking ✓ on every line."
            )
            if cols[1].button(f"Confirm all ({len(pending)})", icon=":material/check:", type="primary", use_container_width=True, key="confirm-all"):
                take_snapshot(f"confirm all ({len(pending)} items)")
                for li in pending:
                    li.state = EditState.USER_CONFIRMED
                log("confirm_all", details={"count": len(pending)})
                st.rerun()
            if cols[2].button("Confirm green-band only", icon=":material/check_circle:", use_container_width=True,
                              key="confirm-green",
                              help="Confirm only items with confidence ≥ 0.8"):
                green = [li for li in pending if li.confidence_band == "green"]
                if green:
                    take_snapshot(f"confirm {len(green)} green items")
                    for li in green:
                        li.state = EditState.USER_CONFIRMED
                    log("confirm_green_only", details={"count": len(green)})
                    st.rerun()
                else:
                    st.toast("No green-band items to confirm.", icon="⚠")
            cols[3].caption("Snapshots are pushed to history — *Undo* in the sidebar reverts.")

        # Group by zone for clarity
        zones = sorted({li.zone for li in ss.line_items})
        items_to_remove: list[str] = []

        for zone in zones:
            zone_items = [li for li in ss.line_items if li.zone == zone]
            zone_total = sum(li.total_zar for li in zone_items)
            zone_pending = [li for li in zone_items if li.state in (EditState.AI_SUGGESTED, EditState.USER_EDITED)]
            locked = zone in ss.locked_zones
            zone_label = f"{'🔒 ' if locked else ''}{zone}  —  R {zone_total:,.2f}  ({len(zone_items)} items)"
            with st.expander(zone_label, expanded=True):
                if zone_pending:
                    zb = st.columns([4, 1])
                    zb[0].caption(f"{len(zone_pending)} item(s) in this zone need confirmation.")
                    if zb[1].button(f"Confirm zone ({len(zone_pending)})", icon=":material/check:", key=f"confirm-zone-{zone}", use_container_width=True):
                        take_snapshot(f"confirm zone {zone}")
                        for li in zone_pending:
                            li.state = EditState.USER_CONFIRMED
                        log("confirm_zone", details={"zone": zone, "count": len(zone_pending)})
                        st.rerun()
                h = st.columns([3.5, 0.9, 0.9, 0.7, 1.2, 1, 1.3, 0.4])
                h[0].markdown("**Description / provenance**")
                h[1].markdown("**Trade**")
                h[2].markdown("**Qty**")
                h[3].markdown("**Unit**")
                h[4].markdown("**Rate (ZAR)**")
                h[5].markdown("**Total**")
                h[6].markdown("**State / conf.**")
                h[7].markdown("🗑")

                for li in zone_items:
                    c = st.columns([3.5, 0.9, 0.9, 0.7, 1.2, 1, 1.3, 0.4])
                    band = li.confidence_band
                    pill = {"green": "🟢", "amber": "🟡", "red": "🔴"}[band]

                    with c[0]:
                        marker = "💰 " if li.high_value_review else ""
                        new_desc = st.text_input(
                            "description",
                            value=li.description,
                            key=f"desc-{li.id}",
                            label_visibility="collapsed",
                        )
                        if new_desc != li.description:
                            log("edit_description", li.id, before=li.description, after=new_desc)
                            li.description = new_desc
                            if li.state == EditState.AI_SUGGESTED:
                                li.state = EditState.USER_EDITED
                        if marker:
                            st.caption(f"{marker}High-value item")
                        prov_bits = [f"📷 {li.provenance.source_image}"]
                        if li.provenance.evidence:
                            prov_bits.append(li.provenance.evidence)
                        st.caption(" · ".join(prov_bits))
                        if li.notes:
                            st.caption(f"📝 {li.notes}")
                        for hint in ss.learner_hints.get(li.id, []):
                            st.caption(hint)
                        for w in li.sanity_warnings:
                            st.caption(w)

                    TRADE_OPTIONS = ["drywall", "tiling", "painting", "plumbing", "electrical",
                                     "carpentry", "masonry", "glazing", "finishes", "demolition", "pgs", "other"]
                    UNIT_OPTIONS = ["m", "m2", "lin.m", "each", "kg", "hr", "no"]
                    with c[1]:
                        try:
                            t_idx = TRADE_OPTIONS.index(li.trade)
                        except ValueError:
                            TRADE_OPTIONS = TRADE_OPTIONS + [li.trade]
                            t_idx = len(TRADE_OPTIONS) - 1
                        new_trade = st.selectbox(
                            "trade", TRADE_OPTIONS, index=t_idx,
                            key=f"trade-{li.id}", label_visibility="collapsed",
                        )
                        if new_trade != li.trade:
                            log("edit_trade", li.id, before=li.trade, after=new_trade)
                            li.trade = new_trade
                            if li.state == EditState.AI_SUGGESTED:
                                li.state = EditState.USER_EDITED
                    with c[2]:
                        new_qty = st.number_input("qty", value=float(li.quantity), min_value=0.0, step=0.1,
                                                  key=f"qty-{li.id}", label_visibility="collapsed")
                    with c[3]:
                        u_idx = UNIT_OPTIONS.index(li.unit) if li.unit in UNIT_OPTIONS else 0
                        new_unit = st.selectbox(
                            "unit", UNIT_OPTIONS, index=u_idx,
                            key=f"unit-{li.id}", label_visibility="collapsed",
                        )
                        if new_unit != li.unit:
                            log("edit_unit", li.id, before=li.unit, after=new_unit)
                            li.unit = new_unit
                            if li.state == EditState.AI_SUGGESTED:
                                li.state = EditState.USER_EDITED
                    with c[4]:
                        new_rate = st.number_input("rate", value=float(li.rate_zar), min_value=0.0, step=10.0,
                                                   key=f"rate-{li.id}", label_visibility="collapsed")

                    edited = False
                    if new_qty != li.quantity:
                        log("edit_quantity", li.id, before=li.quantity, after=new_qty)
                        baseline_qty = ss.ai_baseline.get(li.id, {}).get("qty", li.quantity)
                        memory.record_qty_edit(li.rate_code, li.description, baseline_qty, new_qty)
                        li.quantity = new_qty
                        edited = True
                    if new_rate != li.rate_zar:
                        log("edit_rate", li.id, before=li.rate_zar, after=new_rate)
                        baseline_rate = ss.ai_baseline.get(li.id, {}).get("rate", li.rate_zar)
                        memory.record_rate_edit(li.rate_code, li.description, baseline_rate, new_rate)
                        li.rate_zar = new_rate
                        edited = True
                    if edited and li.state == EditState.AI_SUGGESTED:
                        li.state = EditState.USER_EDITED

                    c[5].markdown(f"**R {li.total_zar:,.2f}**")

                    with c[6]:
                        state_label = li.state.value.replace("_", " ")
                        rate_age = f" · rate {li.rate_age_days}d" if li.rate_age_days is not None else ""
                        st.markdown(f"{pill} `{li.confidence:.2f}` · {state_label}{rate_age}")
                        if li.state in (EditState.AI_SUGGESTED, EditState.USER_EDITED):
                            if st.button("Confirm", icon=":material/check:", key=f"confirm-{li.id}"):
                                take_snapshot(f"confirm {li.description[:30]}")
                                li.state = EditState.USER_CONFIRMED
                                log("confirm_item", li.id)
                                st.rerun()

                    with c[7]:
                        if st.button("", icon=":material/delete:", key=f"del-{li.id}", help="Remove line item"):
                            items_to_remove.append(li.id)

        if items_to_remove:
            take_snapshot(f"remove {len(items_to_remove)} item(s)")
            for rid in items_to_remove:
                log("remove_item", rid)
            ss.line_items = [i for i in ss.line_items if i.id not in items_to_remove]
            st.rerun()

        # ----- Manual add -----
        with st.expander("Add manual line item", icon=":material/add:"):
            # Learned items from past quotes (sub-categorized by trade) — defensive fetch
            try:
                learned = memory.list_learned_items() or []
            except Exception:
                learned = []
            learned = [li for li in learned if li and li.get("description") and li.get("trade")]
            if learned:
                st.markdown("**📚 Pick from learned items (your own catalog, grows with each issued quote)**")
                trades = sorted({li["trade"] for li in learned})
                lcols = st.columns([1, 3])
                with lcols[0]:
                    pick_trade = st.selectbox("Trade", options=["(any)"] + trades, key="learned-trade")
                with lcols[1]:
                    filtered = learned if pick_trade == "(any)" else [li for li in learned if li["trade"] == pick_trade]
                    # Group label format: "Trade > Subcategory · description (R X / unit) · used N×"
                    def _opt(li):
                        rate = li.get("median_rate") or li.get("last_rate") or 0
                        sub = li.get("subcategory") or ""
                        sub_part = f" > {sub}" if sub else ""
                        return (
                            f"[{li.get('trade', '')}{sub_part}] "
                            f"{(li.get('description') or '')[:60]} "
                            f"· R {rate:,.0f}/{li.get('unit', '')} · {li.get('frequency', 0)}×"
                        )
                    options = ["— none —"] + [_opt(li) for li in filtered]
                    pick_li = st.selectbox("Item", options=options, key="learned-item-pick")
                if pick_li != "— none —" and st.button("Add this learned item", icon=":material/add:", key="learned-add"):
                    idx = options.index(pick_li) - 1
                    src = filtered[idx]
                    take_snapshot("add learned item")
                    ss.line_items.append(
                        LineItem(
                            id=uuid.uuid4().hex[:8],
                            description=src["description"],
                            trade=src["trade"],
                            quantity=1.0,
                            unit=src["unit"],
                            zone="Default",
                            rate_zar=float(src["median_rate"] or src["last_rate"] or 0),
                            rate_code=None,
                            confidence=1.0,
                            provenance=Provenance(source_image="learned-catalog",
                                                  evidence=f"learned from {src['frequency']} past use(s)"),
                            state=EditState.USER_ADDED,
                        )
                    )
                    log("add_from_learned", details={"description": src["description"], "rate": src["median_rate"]})
                    st.rerun()
                st.divider()

            rates = load_rates()
            rate_options = ["— custom —"] + [f"{r.code} · {r.description} (R {r.rate_zar:.0f}/{r.unit})" for r in rates]
            col1, col2, col3, col4, col5 = st.columns([2.5, 1.5, 1, 1, 1])
            with col1:
                rate_pick = st.selectbox("Catalogue rate", rate_options, key="manual-rate-pick")
            with col2:
                man_desc = st.text_input("Description", key="manual-desc")
            with col3:
                man_qty = st.number_input("Quantity", min_value=0.0, value=1.0, step=0.5, key="manual-qty")
            with col4:
                existing_zones = sorted({li.zone for li in ss.line_items}) or ["Default"]
                man_zone = st.selectbox("Zone", existing_zones + ["+ new zone"], key="manual-zone")
                if man_zone == "+ new zone":
                    man_zone = st.text_input("New zone name", value="Default", key="manual-zone-new")
            with col5:
                if st.button("Add", icon=":material/add:", key="manual-add"):
                    take_snapshot("add manual item")
                    if rate_pick == "— custom —":
                        if not man_desc:
                            st.warning("Description required for custom item.")
                        else:
                            ss.line_items.append(
                                LineItem(
                                    id=uuid.uuid4().hex[:8],
                                    description=man_desc,
                                    trade="other",
                                    quantity=man_qty,
                                    unit="each",
                                    zone=man_zone or "Default",
                                    rate_zar=0.0,
                                    confidence=1.0,
                                    provenance=Provenance(source_image="manual-entry", evidence="user-added"),
                                    state=EditState.USER_ADDED,
                                )
                            )
                            log("add_manual", details={"description": man_desc, "zone": man_zone})
                            st.rerun()
                    else:
                        code = rate_pick.split(" ", 1)[0]
                        rate = next((r for r in rates if r.code == code), None)
                        if rate:
                            ss.line_items.append(
                                LineItem(
                                    id=uuid.uuid4().hex[:8],
                                    description=rate.description,
                                    trade=rate.trade,
                                    quantity=man_qty,
                                    unit=rate.unit,
                                    zone=man_zone or "Default",
                                    rate_zar=rate.rate_zar,
                                    rate_code=rate.code,
                                    rate_age_days=rate.age_days(),
                                    confidence=1.0,
                                    provenance=Provenance(source_image="manual-entry", evidence=f"catalogue rate {rate.code}"),
                                    state=EditState.USER_ADDED,
                                )
                            )
                            log("add_from_catalogue", details={"code": rate.code, "zone": man_zone})
                            st.rerun()

    # ----- Similar past jobs -----
    if ss.line_items:
        similar = learner.similar_quotes(ss.line_items, top_k=3)
        avg_similar = sum(s["total_zar"] for s in similar) / len(similar) if similar else None

        if similar:
            st.divider()
            st.subheader("💡 Suggestions from similar past jobs")
            for s in similar:
                with st.container(border=True):
                    st.markdown(
                        f"**Past quote `{s['id']}`** — issued {s['issued_at']} · "
                        f"total **R {s['total_zar']:,.2f}** · similarity {s['similarity']:.0%}"
                    )
                    if not s["suggested_items"]:
                        st.caption("All items from this past quote are already in your draft.")
                        continue
                    st.caption("Items in that job but missing from your draft:")
                    for sug_idx, sug in enumerate(s["suggested_items"]):
                        cols = st.columns([3.5, 1, 1, 1, 1.5, 1])
                        cols[0].markdown(f"**{sug.get('description', '')}**")
                        cols[1].write(sug.get("trade", ""))
                        cols[2].write(f"{float(sug.get('quantity', 0)):.2f}")
                        cols[3].write(sug.get("unit", ""))
                        cols[4].write(f"R {float(sug.get('rate_zar', 0)):,.2f}/{sug.get('unit', '')}")
                        # Include loop index in key — two items can share rate_code (or both None) and collide
                        if cols[5].button("Add", icon=":material/add:", key=f"add-{s['id']}-{sug.get('rate_code') or 'norate'}-{sug_idx}"):
                            take_snapshot("add from similar job")
                            new_id = uuid.uuid4().hex[:8]
                            ss.line_items.append(
                                LineItem(
                                    id=new_id,
                                    description=sug["description"],
                                    trade=sug["trade"],
                                    quantity=sug["quantity"],
                                    unit=sug["unit"],
                                    rate_zar=sug["rate_zar"],
                                    rate_code=sug["rate_code"],
                                    confidence=1.0,
                                    provenance=Provenance(
                                        source_image="learner-suggestion",
                                        evidence=f"suggested from past quote {s['id']}",
                                    ),
                                    state=EditState.USER_ADDED,
                                )
                            )
                            log("add_from_similar_quote", new_id, source_quote=s["id"], rate_code=sug["rate_code"])
                            st.rerun()

        # ----- Quote summary + anomalies + issue -----
        st.divider()
        st.subheader("3. Quote summary")

        anomalies = validators.quote_level_anomalies(ss.line_items, similar_avg_total=avg_similar)
        if anomalies:
            with st.container(border=True):
                st.markdown("**⚠ Quote-level anomalies — review before issue**")
                for a in anomalies:
                    st.markdown(f"- {a}")

        # ----- Verbal edits (B-mode): speak instructions, AI applies them -----
        if _stt is not None and parse_voice_instruction is not None and ss.frozen_quote is None:
            # Collapsed by default — expand if there are pending edits to confirm
            voice_default_open = bool(ss.get("voice_edit_pending"))
            with st.expander("Verbal edit before issue", expanded=voice_default_open, icon=":material/mic:"):
                st.caption("Say something like *'drop carpenter rate by 10%, add a labourer day, change RE to mention weekend'*. AI parses → diff preview → confirm before applying.")
                vcols = st.columns([1, 4])
                with vcols[0]:
                    spoken = _stt(
                        language="en-ZA",
                        start_prompt="🎙 Speak edit",
                        stop_prompt="⏹ Stop",
                        just_once=True,
                        use_container_width=True,
                        key=f"voice-edit-stt-{ss.voice_seq}",
                    )
                with vcols[1]:
                    st.caption(
                        "AI parses instructions into structured edits, shows a diff preview, "
                        "you confirm before applying. Free — no extra API key needed beyond Claude."
                    )
                if spoken:
                    if not providers.has_provider_key():
                        st.error("Anthropic key needed for voice-edit parsing — paste it in the sidebar.")
                    else:
                        with st.spinner("Parsing your instruction…"):
                            parsed = parse_voice_instruction(spoken, ss.line_items, ss.quote_header)
                        if parsed and parsed.get("edits"):
                            ss.voice_edit_pending = {
                                "transcript": spoken,
                                "edits": parsed["edits"],
                                "summary": parsed.get("summary", ""),
                            }
                            ss.voice_seq += 1
                            st.rerun()
                        else:
                            st.warning(f"Couldn't parse anything actionable. Heard: \"{spoken}\"")

                # Diff preview if edits are pending
                if ss.get("voice_edit_pending"):
                    pe = ss.voice_edit_pending
                    st.markdown(f"**Heard:** *\"{pe['transcript']}\"*")
                    if pe.get("summary"):
                        st.markdown(f"**Plan:** {pe['summary']}")
                    st.markdown(f"**{len(pe['edits'])} edit(s) proposed:**")
                    for i, e in enumerate(pe["edits"]):
                        op = e.get("op", "?")
                        reasoning = e.get("reasoning", "")
                        if op == "modify_item":
                            tid = e.get("target_item_id", "?")
                            li = next((x for x in ss.line_items if x.id == tid), None)
                            target_desc = li.description[:50] if li else f"item {tid}"
                            field = e.get("field", "?")
                            change = ""
                            if "delta_pct" in e and e["delta_pct"] is not None:
                                change = f"{field} {e['delta_pct']:+.1f}%"
                            elif "value" in e:
                                change = f"{field} → {e['value']}"
                            st.markdown(f"- **MODIFY** *{target_desc}*: {change}  *({reasoning})*")
                        elif op == "remove_item":
                            tid = e.get("target_item_id", "?")
                            li = next((x for x in ss.line_items if x.id == tid), None)
                            target_desc = li.description[:50] if li else f"item {tid}"
                            st.markdown(f"- **REMOVE** *{target_desc}*  *({reasoning})*")
                        elif op == "add_item":
                            ni = e.get("new_item") or {}
                            st.markdown(f"- **ADD** *{ni.get('description', '?')[:50]}*: {ni.get('quantity')} {ni.get('unit')} @ R{ni.get('rate_zar', 0)}  *({reasoning})*")
                        elif op == "modify_header":
                            st.markdown(f"- **HEADER** {e.get('field')} → {e.get('value')!r}  *({reasoning})*")
                    apply_cols = st.columns(2)
                    if apply_cols[0].button("Apply edits", icon=":material/check:", type="primary", use_container_width=True, key=f"voice-apply-{ss.voice_seq}"):
                        take_snapshot(f"voice edit: {pe.get('summary', 'verbal')[:40]}")
                        ss.line_items, ss.quote_header, applied_log = _apply_voice_edits(
                            ss.line_items, ss.quote_header, pe["edits"]
                        )
                        ss.voice_edit_pending = None
                        ss.voice_seq += 1
                        log("voice_edit_applied", details={"summary": pe.get("summary", ""), "applied": applied_log})
                        st.toast(f"Applied {len(applied_log)} change(s)", icon="✅")
                        st.rerun()
                    if apply_cols[1].button("Discard", icon=":material/close:", use_container_width=True, key=f"voice-discard-{ss.voice_seq}"):
                        ss.voice_edit_pending = None
                        ss.voice_seq += 1
                        st.rerun()

        sub_col, action_col = st.columns([2, 1])
        with sub_col:
            subs = trade_subtotals(ss.line_items)
            for trade, subtotal in sorted(subs.items(), key=lambda x: -x[1]):
                st.markdown(f"- **{trade.title()}** — R {subtotal:,.2f}")
            st.markdown(f"### Total: R {quote_total(ss.line_items):,.2f}")

        with action_col:
            ok, blockers = can_issue(ss.line_items)
            if ss.frozen_quote is not None:
                st.success(f"Quote issued at {ss.frozen_quote['issued_at']}")
                if ss.get("last_saved_dir"):
                    st.info(f"💾 Auto-saved to: `{ss.last_saved_dir}`")
                elif ss.get("last_saved_error"):
                    st.warning(f"Auto-save failed: {ss.last_saved_error}. PDF/Excel still downloadable below.")
                # Use the readable filename convention everywhere
                base_name = _quote_filename_base(ss.frozen_quote)
                try:
                    pdf_bytes = render_quote_pdf(ss.frozen_quote)
                except Exception as e:
                    pdf_bytes = b""
                    st.error(f"PDF render failed: {e}")
                xlsx_bytes = issued_quote_to_xlsx(ss.frozen_quote)

                d1, d2 = st.columns(2)
                with d1:
                    if pdf_bytes:
                        st.download_button(
                            "Download PDF", icon=":material/picture_as_pdf:",
                            data=pdf_bytes,
                            file_name=f"{base_name}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True,
                        )
                with d2:
                    st.download_button(
                        "Download Excel", icon=":material/grid_on:",
                        data=xlsx_bytes,
                        file_name=f"{base_name}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

                if pdf_bytes:
                    with st.expander("Preview PDF (in-app)", expanded=True, icon=":material/preview:"):
                        try:
                            pages_png = pdf_pages_to_pngs(pdf_bytes, scale=1.5)
                            if len(pages_png) > 1:
                                st.caption(f"Showing all {len(pages_png)} pages.")
                            for label, png in pages_png:
                                st.image(png, caption=label, use_container_width=True)
                        except Exception as e:
                            st.warning(f"Could not render PDF preview inline: {e}")

                with st.expander("Also download as JSON", icon=":material/code:"):
                    st.download_button(
                        "Download JSON snapshot",
                        data=json.dumps(ss.frozen_quote, indent=2, default=str),
                        file_name=f"{base_name}.json",
                        mime="application/json",
                    )
            else:
                # Required-field gate: client + project both must be set
                missing_client = not (ss.quote_header.get("client_name") or "").strip()
                missing_project = not (ss.quote_header.get("project") or "").strip()
                hard_block = missing_client or missing_project
                if hard_block:
                    bits = []
                    if missing_client: bits.append("**Client**")
                    if missing_project: bits.append("**Project**")
                    st.error(f"❗ Required: {' and '.join(bits)} must be selected (or added) in the Quote header before issuing.")

                st.markdown('<div class="qs-divider"></div>', unsafe_allow_html=True)
                st.markdown('<div class="qs-sticky-action">', unsafe_allow_html=True)
                issue_btn = st.button("Issue Quote (strict, reviewed)",
                                      icon=":material/check_circle:", type="primary",
                                      disabled=(not ok) or hard_block,
                                      use_container_width=True)
                quick_btn = st.button(
                    "Quick Excel (skip review)",
                    icon=":material/bolt:",
                    help="Bypass per-item review and immediately generate the Excel/PDF from whatever AI extracted. Use when you plan to edit the Excel yourself.",
                    disabled=(not ss.line_items) or hard_block,
                    use_container_width=True,
                )
                st.markdown('</div>', unsafe_allow_html=True)
                if not ok:
                    summary = blocker_summary(ss.line_items)
                    if summary["empty"]:
                        st.caption("Quote has no line items.")
                    else:
                        st.markdown(f"**⚠ Strict mode — {len(summary['categories'])} blocker categor(ies), {summary['total']} item(s)**")
                        for cat in summary["categories"]:
                            st.markdown(f"- {cat['label']}")
                        st.caption("…or use 🚀 *Quick Excel* above to issue immediately and edit the file yourself.")
                        with st.expander("Show every blocked item id (raw list)"):
                            for b in blockers:
                                st.markdown(f"- {b}")
                if issue_btn and ok:
                    ss.frozen_quote = freeze_quote(ss.line_items, header=ss.quote_header)
                    quote_id = memory.record_issued_quote(ss.frozen_quote, ss.line_items)
                    ss.frozen_quote["memory_id"] = quote_id
                    _record_learning_from_quote(ss.frozen_quote)
                    _autosave_to_work_folder(ss.frozen_quote)
                    log("issue_quote", details={"total_zar": ss.frozen_quote["total_zar"], "memory_id": quote_id})
                    st.rerun()
                if quick_btn and ss.line_items:
                    take_snapshot("quick excel issue (skip review)")
                    for li in ss.line_items:
                        if li.state == EditState.AI_SUGGESTED:
                            li.state = EditState.USER_CONFIRMED
                    ss.frozen_quote = freeze_quote(ss.line_items, header=ss.quote_header)
                    quote_id = memory.record_issued_quote(ss.frozen_quote, ss.line_items)
                    ss.frozen_quote["memory_id"] = quote_id
                    _record_learning_from_quote(ss.frozen_quote)
                    _autosave_to_work_folder(ss.frozen_quote)
                    log("quick_issue", details={
                        "total_zar": ss.frozen_quote["total_zar"],
                        "memory_id": quote_id,
                        "items": len(ss.line_items),
                    })
                    st.rerun()

# ============================================================================
# TAB 2 — PAST QUOTES (browse, search, open as draft / variation)
# ============================================================================

def _load_past_quote_into_workspace(quote_id: str, mode: str) -> bool:
    """Pull a past quote into the active workspace.
    mode = 'view' (frozen, read-only — show downloads), 'draft' (clone items, edit fresh),
    or 'variation' (clone items + client info, fresh quote no., links parent_quote_id).
    """
    payload = memory.get_full_quote(quote_id)
    if not payload:
        return False
    if mode == "view":
        ss.frozen_quote = payload
        ss.line_items = []
        ss.pending_items = []
        log("open_past_quote", details={"quote_id": quote_id, "mode": mode})
        return True

    # mode in ('draft', 'variation') — pull items into editable workspace
    items_data = payload.get("items") or []
    new_items: list[LineItem] = []
    for it in items_data:
        try:
            new_items.append(LineItem(**it))
        except Exception:
            continue

    # Reset workspace
    ss.line_items = new_items
    ss.pending_items = []
    ss.frozen_quote = None
    ss.uploads = {}
    ss.learner_hints = {}
    ss.ai_baseline = {}
    ss.history = []
    ss.unified_inputs = []
    ss.unified_context = ""
    ss.clarification = None

    # Reset every line item to user_added so the user can edit freely
    for li in ss.line_items:
        li.state = EditState.USER_ADDED

    # Header handling: keep company info; pull client info ONLY in 'variation' mode
    src_header = payload.get("header") or {}
    h = ss.quote_header
    if mode == "variation":
        # Carry client + project info from parent
        for f in ("client_name", "client_vat_reg", "client_address", "attention",
                  "project", "labels"):
            if src_header.get(f):
                h[f] = src_header[f]
        # New quote-specific fields generated fresh
        from datetime import datetime
        now = datetime.utcnow()
        h["quote_no"] = "Q-" + now.strftime("%Y%m%d-%H%M")
        h["quote_date"] = f"{now.day} {now.strftime('%B %Y')}"
        h["quote_name"] = (src_header.get("quote_name") or "") + " (variation)" if src_header.get("quote_name") else ""
        h["re_subject"] = src_header.get("re_subject") or ""
        h["expiry_date"] = ""
        h["project_reference"] = ""
        h["parent_quote_id"] = quote_id
    else:
        # 'draft' — wipe per-job fields, keep company defaults
        for f in QuoteHeader.per_job_fields():
            h[f] = ""
    ss.quote_header = h

    log("open_past_quote", details={"quote_id": quote_id, "mode": mode, "items": len(new_items)})
    return True


with tab_past:
    st.subheader("Past quotes")
    st.caption("Search, browse, open and clone every quote you've issued. Variations stay linked to their parent.")

    # Stats strip — at-a-glance overview
    all_quotes_for_stats = memory.list_quotes()
    total_zar = sum((q["total_zar"] or 0) for q in all_quotes_for_stats)
    unique_clients = len({(q["client_name"] or "").strip() for q in all_quotes_for_stats if q["client_name"]})
    unique_projects = len({(q["project"] or "").strip() for q in all_quotes_for_stats if q["project"]})
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.utcnow() - _td(days=7)).isoformat()
    last_7 = sum(1 for q in all_quotes_for_stats if (q["issued_at"] or "") >= cutoff)
    stats_cells = [
        _strip_cell("Total", f"{len(all_quotes_for_stats)} quotes"),
        _strip_cell("Last 7 days", f"{last_7}"),
        _strip_cell("Clients", f"{unique_clients}"),
        _strip_cell("Projects", f"{unique_projects}"),
        _strip_cell("Sum issued", f"R {total_zar:,.0f}"),
    ]
    st.markdown(f'<div class="qs-strip">{"".join(stats_cells)}</div>', unsafe_allow_html=True)

    fcol1, fcol2, fcol3 = st.columns([2, 2, 2])
    with fcol1:
        try:
            _client_rows = memory.list_clients() or []
        except Exception:
            _client_rows = []
        all_clients = sorted({(c.get("name") or "").strip() for c in _client_rows if c.get("name")})
        client_filter = st.selectbox("Client", ["(all)"] + all_clients + ["(no client)"], key="past-client")
    with fcol2:
        try:
            _proj_rows = memory.list_projects() or []
        except Exception:
            _proj_rows = []
        all_projects = sorted({p.get("project") for p in _proj_rows if p.get("project") and p.get("project") != "(no project)"})
        project_filter = st.selectbox("Project", ["(all)"] + all_projects + ["(no project)"], key="past-project")
    with fcol3:
        search_term = st.text_input("Search", value="", key="past-search",
                                    placeholder="quote no. / subject / labels")

    project_arg = None if project_filter == "(all)" else (None if project_filter == "(no project)" else project_filter)
    client_arg = None if client_filter == "(all)" else (None if client_filter == "(no client)" else client_filter)
    quotes = memory.list_quotes(
        project=project_arg,
        client_name=client_arg,
        search=search_term.strip() or None,
    )
    if project_filter == "(no project)":
        quotes = [q for q in quotes if not q["project"]]
    if client_filter == "(no client)":
        quotes = [q for q in quotes if not q["client_name"]]

    if not quotes:
        st.info("No issued quotes match. Issue a quote from the Quote builder tab to see it here.")
    else:
        # Two-level grouping: client → project → quotes
        by_client_project: dict[str, dict[str, list]] = {}
        for q in quotes:
            client_key = q["client_name"] or "(no client)"
            project_key = q["project"] or "(no project)"
            by_client_project.setdefault(client_key, {}).setdefault(project_key, []).append(q)

        for client_name in sorted(by_client_project.keys()):
            projects = by_client_project[client_name]
            client_quote_count = sum(len(g) for g in projects.values())
            client_total = sum(sum((q["total_zar"] or 0) for q in g) for g in projects.values())
            project_count = len(projects)
            with st.expander(
                f"**{client_name}** · {project_count} project(s) · {client_quote_count} quote(s) · R {client_total:,.2f}",
                expanded=True,
                icon=":material/business:",
            ):
                for project_name in sorted(projects.keys()):
                    group = projects[project_name]
                    project_total = sum((q["total_zar"] or 0) for q in group)
                    if project_count > 1 or project_name != "(no project)":
                        st.markdown(
                            f'<div style="margin:14px 0 6px 0; padding:6px 10px; '
                            f'background:#F4F8FA; border-left:3px solid #13B5EA; border-radius:6px;">'
                            f'<b style="color:#0A2540">{project_name}</b> '
                            f'<span style="color:#475569; font-size:0.9em">'
                            f'· {len(group)} quote(s) · R {project_total:,.2f}</span></div>',
                            unsafe_allow_html=True,
                        )
                    for q in group:
                        st.markdown(_quote_card(dict(q)), unsafe_allow_html=True)
                        bcols = st.columns([1, 1, 1, 1, 1])
                        with bcols[0]:
                            if st.button("View", icon=":material/visibility:",
                                         key=f"view-{q['id']}", use_container_width=True):
                                if _load_past_quote_into_workspace(q["id"], mode="view"):
                                    st.toast("Loaded as read-only — switch to Quote builder tab to download.")
                                    st.rerun()
                        with bcols[1]:
                            if st.button("Open as draft", icon=":material/edit:",
                                         key=f"draft-{q['id']}", use_container_width=True,
                                         help="Pull items into a fresh editable draft. Client/quote info reset."):
                                if _load_past_quote_into_workspace(q["id"], mode="draft"):
                                    st.toast("Opened as a draft — switch to Quote builder tab.")
                                    st.rerun()
                        with bcols[2]:
                            if st.button("New variation", icon=":material/content_copy:",
                                         key=f"var-{q['id']}", use_container_width=True,
                                         help="Clone items AND client info; fresh quote no. and date. Links to parent."):
                                if _load_past_quote_into_workspace(q["id"], mode="variation"):
                                    st.toast("Opened as a variation — same client, same project, fresh quote.")
                                    st.rerun()
                        with bcols[3]:
                            if st.button("Convert to invoice", icon=":material/request_quote:",
                                         key=f"inv-from-{q['id']}", use_container_width=True,
                                         help="Create a draft tax invoice from this quote (15% VAT, 30-day terms). Open the Invoices tab to edit/issue."):
                                try:
                                    new_inv_id = invoices.convert_quote_to_invoice(q["id"])
                                    log("invoice_created_from_quote", details={
                                        "invoice_id": new_inv_id, "quote_id": q["id"],
                                    })
                                    st.toast(f"Draft invoice created — see Invoices tab.", icon="🧾")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed to create invoice: {e}")


# ============================================================================
# TAB 3 — INVOICES (Pastel-equivalent for SA construction)
# ============================================================================

with tab_invoices:
    st.subheader("Invoices & receivables")
    st.caption(
        "Convert issued quotes to tax invoices, record payments, track aged debtors, "
        "and issue per-client statements. SARS-compliant tax invoice format (15% VAT)."
    )

    sub_inv_list, sub_aged, sub_statements = st.tabs([
        ":material/list_alt: Invoices",
        ":material/insights: Aged debtors",
        ":material/description: Statements",
    ])

    # ---- Invoice list / detail ---------------------------------------------
    with sub_inv_list:
        # Filter row
        f1, f2, f3 = st.columns([2, 2, 1])
        with f1:
            inv_filter_client = st.selectbox(
                "Client",
                options=["(all)"] + [c["name"] for c in memory.list_clients()],
                key="inv-flt-client",
            )
        with f2:
            inv_filter_status = st.selectbox(
                "Status",
                options=["(all)", "draft", "issued", "partial", "paid", "void"],
                key="inv-flt-status",
            )
        with f3:
            if st.button("Refresh", icon=":material/refresh:", use_container_width=True, key="inv-refresh"):
                st.rerun()

        client_arg = None if inv_filter_client == "(all)" else inv_filter_client
        status_arg = None if inv_filter_status == "(all)" else inv_filter_status
        inv_rows = invoices.list_invoices(client_name=client_arg, status=status_arg)

        if not inv_rows:
            st.info(
                "No invoices yet. Create one from the **Past quotes** tab "
                "(Convert to invoice button) or add a manual invoice below."
            )
        else:
            # Summary metrics
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Invoices", str(len(inv_rows)))
            with m2:
                st.metric("Total invoiced", f"R {sum(r['total'] for r in inv_rows):,.0f}")
            with m3:
                st.metric("Paid to date", f"R {sum(r['paid_total'] for r in inv_rows):,.0f}")
            with m4:
                st.metric("Outstanding", f"R {sum(r['balance'] for r in inv_rows):,.0f}")

            st.markdown("---")
            # Status → plain text label for expander title (Streamlit doesn't
            # render HTML in expander labels). Inside each expander we show a
            # styled qs-pill badge for visual consistency.
            STATUS_LABEL = {
                "draft":   "Draft",
                "issued":  "Issued",
                "partial": "Partial",
                "paid":    "Paid",
                "void":    "Void",
            }
            STATUS_PILL_CLASS = {
                "draft":   "qs-pill-grey",
                "issued":  "qs-pill-info",
                "partial": "qs-pill-amber",
                "paid":    "qs-pill-green",
                "void":    "qs-pill-grey",
            }
            for inv in inv_rows:
                title = f"{inv['invoice_no']} · {inv['client_name']} · R {inv['total']:,.2f} · {STATUS_LABEL.get(inv['status'], inv['status'])}"
                if inv["balance"] > 0:
                    title += f" · balance R {inv['balance']:,.2f}"
                with st.expander(title, expanded=False):
                    full = invoices.get_invoice(inv["id"])
                    if not full:
                        st.error("Invoice missing.")
                        continue
                    # Header info + styled status pill
                    pill_class = STATUS_PILL_CLASS.get(full["status"], "qs-pill-grey")
                    pill_label = STATUS_LABEL.get(full["status"], full["status"])
                    st.markdown(
                        f'<span class="qs-pill {pill_class}">{pill_label}</span>',
                        unsafe_allow_html=True,
                    )
                    cols = st.columns([2, 2, 2])
                    with cols[0]:
                        st.markdown(f"**Date:** {full['invoice_date']}")
                        st.markdown(f"**Due:** {full['due_date']}")
                        if full.get("project_name"):
                            st.markdown(f"**Project:** {full['project_name']}")
                    with cols[1]:
                        st.markdown(f"**Subtotal:** R {full['subtotal']:,.2f}")
                        st.markdown(f"**VAT @ {full['vat_pct']:g}%:** R {full['vat_amount']:,.2f}")
                        if full.get("retention_amount"):
                            st.markdown(f"**Retention ({full['retention_pct']:g}%):** R {full['retention_amount']:,.2f}")
                        st.markdown(f"**Total:** R {full['total']:,.2f}")
                    with cols[2]:
                        st.markdown(f"**Paid:** R {full['paid_total']:,.2f}")
                        balance_color = "#DC2626" if full['balance'] > 0.005 else "#16A34A"
                        st.markdown(
                            f'<span style="font-size:1.05rem; font-weight:600;">Balance: '
                            f'<span style="color:{balance_color}">R {full["balance"]:,.2f}</span></span>',
                            unsafe_allow_html=True,
                        )

                    # Line items
                    if full["lines"]:
                        st.markdown("**Lines:**")
                        line_rows = [
                            {
                                "Description": ln["description"],
                                "Qty": ln["quantity"],
                                "Unit": ln["unit"],
                                "Rate": f"R {ln['rate']:,.2f}",
                                "Amount": f"R {ln['amount']:,.2f}",
                            }
                            for ln in full["lines"]
                        ]
                        st.dataframe(line_rows, use_container_width=True, hide_index=True)

                    # Payments
                    if full["payments"]:
                        st.markdown("**Payments:**")
                        for p in full["payments"]:
                            pcols = st.columns([3, 1])
                            with pcols[0]:
                                ref_bit = f" · ref {p['reference']}" if p.get("reference") else ""
                                st.markdown(f"• {p['payment_date']} · R {p['amount']:,.2f} · {p.get('method') or 'EFT'}{ref_bit}")
                            with pcols[1]:
                                if st.button("Delete", icon=":material/delete:", key=f"del-pay-{p['id']}", use_container_width=True):
                                    invoices.delete_payment(p["id"])
                                    log("payment_deleted", details={"payment_id": p["id"], "invoice_id": full["id"]})
                                    st.rerun()

                    # Inline "Record payment" — no nested expander, three taps to log a payment
                    if full["balance"] > 0.005:
                        st.markdown('<div class="qs-divider"></div>', unsafe_allow_html=True)
                        st.markdown("**Record payment**")
                        pcol1, pcol2, pcol3, pcol4 = st.columns([1.2, 1, 1.2, 1])
                        with pcol1:
                            pay_amount = st.number_input(
                                "Amount",
                                min_value=0.0,
                                max_value=float(full["balance"]),
                                value=float(full["balance"]),
                                step=100.0,
                                key=f"pay-amt-{full['id']}",
                            )
                        with pcol2:
                            pay_date = st.date_input("Date", key=f"pay-date-{full['id']}")
                        with pcol3:
                            pay_method = st.selectbox(
                                "Method",
                                options=["EFT", "Cash", "Card", "Cheque", "Other"],
                                key=f"pay-method-{full['id']}",
                            )
                        with pcol4:
                            st.markdown("&nbsp;", unsafe_allow_html=True)  # vertical alignment
                            save_clicked = st.button(
                                "Save", icon=":material/check:",
                                type="primary",
                                key=f"pay-save-{full['id']}",
                                use_container_width=True,
                            )
                        pay_ref = st.text_input(
                            "Reference / bank statement line (optional)",
                            key=f"pay-ref-{full['id']}",
                            placeholder="e.g. ABSA EFT 12345",
                        )
                        if save_clicked:
                            if pay_amount > 0:
                                invoices.record_payment(
                                    full["id"],
                                    amount=pay_amount,
                                    payment_date=pay_date.strftime("%Y-%m-%d"),
                                    method=pay_method,
                                    reference=pay_ref or None,
                                )
                                log("payment_recorded", details={
                                    "invoice_id": full["id"],
                                    "amount": pay_amount,
                                    "method": pay_method,
                                })
                                st.toast(f"Payment of R {pay_amount:,.2f} recorded", icon="✅")
                                st.rerun()

                    # Actions
                    acol1, acol2, acol3, acol4 = st.columns(4)
                    with acol1:
                        # Status change
                        new_status = st.selectbox(
                            "Status",
                            options=["draft", "issued", "partial", "paid", "void"],
                            index=["draft", "issued", "partial", "paid", "void"].index(full["status"]),
                            key=f"inv-status-{full['id']}",
                            label_visibility="collapsed",
                        )
                        if new_status != full["status"]:
                            invoices.update_invoice_status(full["id"], new_status)
                            log("invoice_status_changed", details={
                                "invoice_id": full["id"], "from": full["status"], "to": new_status,
                            })
                            st.rerun()
                    with acol2:
                        # PDF download
                        try:
                            company_data = company_profile.load_profile()
                            pdf_bytes = render_invoice_pdf(full, company_data)
                            st.download_button(
                                "Tax invoice PDF",
                                icon=":material/picture_as_pdf:",
                                data=pdf_bytes,
                                file_name=f"{full['invoice_no']}.pdf",
                                mime="application/pdf",
                                use_container_width=True,
                                key=f"inv-pdf-{full['id']}",
                            )
                        except Exception as e:
                            st.error(f"PDF render failed: {e}")
                    with acol3:
                        if st.button("Delete invoice", icon=":material/delete:", key=f"inv-del-{full['id']}", use_container_width=True):
                            invoices.delete_invoice(full["id"])
                            log("invoice_deleted", details={"invoice_id": full["id"]})
                            st.rerun()

        # Manual invoice creation
        st.markdown("---")
        with st.expander("Add manual invoice", icon=":material/add:"):
            mcols = st.columns([2, 2, 1, 1])
            with mcols[0]:
                m_client = st.selectbox(
                    "Client",
                    options=[c["name"] for c in memory.list_clients()] + ["(new)"],
                    key="man-inv-client",
                )
            with mcols[1]:
                m_project = st.selectbox(
                    "Project",
                    options=["(none)"] + [p["name"] for p in memory.list_projects_admin()],
                    key="man-inv-project",
                )
            with mcols[2]:
                m_vat = st.number_input("VAT %", value=15.0, step=0.5, key="man-inv-vat")
            with mcols[3]:
                m_retention = st.number_input("Retention %", value=0.0, step=1.0, key="man-inv-ret")

            m_subject = st.text_input("RE: subject", key="man-inv-subject")

            st.caption("Add line items below — at least one is required.")
            if "manual_inv_lines" not in ss:
                ss.manual_inv_lines = []
            ml_cols = st.columns([3, 1, 1, 1, 1])
            with ml_cols[0]:
                ml_desc = st.text_input("Description", key="man-inv-ld")
            with ml_cols[1]:
                ml_qty = st.number_input("Qty", value=1.0, step=1.0, key="man-inv-lq")
            with ml_cols[2]:
                ml_unit = st.text_input("Unit", value="no", key="man-inv-lu")
            with ml_cols[3]:
                ml_rate = st.number_input("Rate", value=0.0, step=100.0, key="man-inv-lr")
            with ml_cols[4]:
                if st.button("Add line", icon=":material/add:", key="man-inv-laddln", use_container_width=True):
                    if ml_desc.strip() and ml_qty > 0:
                        ss.manual_inv_lines.append({
                            "description": ml_desc.strip(),
                            "quantity": float(ml_qty),
                            "unit": ml_unit or "no",
                            "rate": float(ml_rate),
                        })
                        st.rerun()

            if ss.manual_inv_lines:
                st.markdown("**Pending lines:**")
                for i, ln in enumerate(ss.manual_inv_lines):
                    pcols = st.columns([5, 1])
                    with pcols[0]:
                        st.markdown(f"• {ln['description']} — {ln['quantity']} {ln['unit']} @ R {ln['rate']:,.2f}")
                    with pcols[1]:
                        if st.button("Remove", key=f"man-inv-rm-{i}"):
                            ss.manual_inv_lines.pop(i)
                            st.rerun()

                if st.button("Create draft invoice", icon=":material/check:", type="primary", key="man-inv-create"):
                    if m_client == "(new)" or not m_client.strip():
                        st.error("Pick or add a client first.")
                    else:
                        proj_name = None if m_project == "(none)" else m_project
                        new_id = invoices.create_invoice(
                            client_name=m_client,
                            project_name=proj_name,
                            lines=ss.manual_inv_lines,
                            vat_pct=m_vat,
                            retention_pct=m_retention,
                            re_subject=m_subject or None,
                            status="draft",
                        )
                        ss.manual_inv_lines = []
                        log("invoice_created_manual", details={"invoice_id": new_id, "client": m_client})
                        st.toast(f"Draft invoice created (id {new_id})", icon="✅")
                        st.rerun()

    # ---- Aged debtors ------------------------------------------------------
    with sub_aged:
        st.markdown("**Aged debtors** — outstanding balances bucketed by days overdue.")
        aged = invoices.aged_debtors()
        if not aged:
            st.info("No outstanding balances. 🎉")
        else:
            # Totals strip
            tot_row = {
                "current": sum(b["current"] for b in aged),
                "b30":     sum(b["b30"] for b in aged),
                "b60":     sum(b["b60"] for b in aged),
                "b90":     sum(b["b90"] for b in aged),
                "b90plus": sum(b["b90plus"] for b in aged),
                "total":   sum(b["total"] for b in aged),
            }
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            with mc1: st.metric("Current",    f"R {tot_row['current']:,.0f}")
            with mc2: st.metric("1–30 days",  f"R {tot_row['b30']:,.0f}")
            with mc3: st.metric("31–60 days", f"R {tot_row['b60']:,.0f}")
            with mc4: st.metric("61–90 days", f"R {tot_row['b90']:,.0f}")
            with mc5: st.metric("90+ days",   f"R {tot_row['b90plus']:,.0f}")
            with mc6: st.metric("**TOTAL**",  f"R {tot_row['total']:,.0f}")

            st.markdown("---")
            table_rows = [
                {
                    "Client": b["client"],
                    "Current": f"R {b['current']:,.2f}",
                    "1–30": f"R {b['b30']:,.2f}",
                    "31–60": f"R {b['b60']:,.2f}",
                    "61–90": f"R {b['b90']:,.2f}",
                    "90+": f"R {b['b90plus']:,.2f}",
                    "Total": f"R {b['total']:,.2f}",
                }
                for b in aged
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

    # ---- Per-client statement ---------------------------------------------
    with sub_statements:
        st.markdown("**Account statement** — running ledger of all invoices and payments per client.")
        stm_cols = st.columns([3, 1, 1])
        with stm_cols[0]:
            stm_client = st.selectbox(
                "Client",
                options=[c["name"] for c in memory.list_clients()],
                key="stm-client",
            )
        with stm_cols[1]:
            stm_from = st.date_input("From", value=None, key="stm-from")
        with stm_cols[2]:
            stm_to = st.date_input("To", value=None, key="stm-to")

        if stm_client:
            stmt = invoices.client_statement(
                stm_client,
                from_date=stm_from.strftime("%Y-%m-%d") if stm_from else None,
                to_date=stm_to.strftime("%Y-%m-%d") if stm_to else None,
            )
            mcA, mcB, mcC = st.columns(3)
            with mcA: st.metric("Invoiced", f"R {stmt['total_invoiced']:,.0f}")
            with mcB: st.metric("Paid",     f"R {stmt['total_paid']:,.0f}")
            with mcC: st.metric("Closing balance", f"R {stmt['closing_balance']:,.0f}")

            if stmt["entries"]:
                st.markdown("---")
                ent_rows = [
                    {
                        "Date": e["date"],
                        "Type": e["type"].title(),
                        "Reference": e["ref"],
                        "Notes": e.get("notes") or "",
                        "Debit": f"R {e['debit']:,.2f}" if e["debit"] else "",
                        "Credit": f"R {e['credit']:,.2f}" if e["credit"] else "",
                        "Balance": f"R {e['balance']:,.2f}",
                    }
                    for e in stmt["entries"]
                ]
                st.dataframe(ent_rows, use_container_width=True, hide_index=True)

                # Download statement PDF
                try:
                    company_data = company_profile.load_profile()
                    stmt_pdf = render_statement_pdf(stmt, company_data)
                    st.download_button(
                        "Download statement PDF",
                        icon=":material/picture_as_pdf:",
                        data=stmt_pdf,
                        file_name=f"statement-{stm_client.replace(' ', '_')}-{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        use_container_width=False,
                        type="primary",
                    )
                except Exception as e:
                    st.error(f"Statement PDF render failed: {e}")
            else:
                st.info(f"No invoices or payments for {stm_client} in this window.")


# ============================================================================
# TAB 4 — CLIENTS & PROJECTS (manage the database explicitly)
# ============================================================================

with tab_admin:
    st.subheader("📇 Clients & Projects")
    st.caption("Add, edit, delete clients and projects. The system also auto-creates entries when you issue a quote, but you can manage them here directly.")

    sub_clients, sub_projects, sub_catalog = st.tabs(["👤 Clients", "📁 Projects", "📚 Catalog"])

    # ---------------- Clients ----------------
    with sub_clients:
        with st.expander("Add new client", icon=":material/add:", expanded=False):
            ac_cols = st.columns(2)
            with ac_cols[0]:
                new_name = st.text_input("Client name *", key="adm-cn-name")
                new_vat = st.text_input("VAT reg.", key="adm-cn-vat")
                new_address = st.text_input("Address / site", key="adm-cn-addr")
            with ac_cols[1]:
                new_attn = st.text_input("Attention (contact name)", key="adm-cn-attn")
                new_contact = st.text_input("Contact (phone / email)", key="adm-cn-contact")
                new_notes = st.text_area("Notes", height=70, key="adm-cn-notes")
            if st.button("Save client", icon=":material/save:", type="primary", key="adm-cn-save"):
                if not new_name.strip():
                    st.error("Client name is required.")
                else:
                    memory.upsert_client(new_name, new_vat, new_address, new_attn, new_contact, new_notes)
                    log("admin_add_client", details={"name": new_name})
                    st.success(f"Saved client: {new_name}")
                    st.rerun()

        try:
            clients_list = memory.list_clients() or []
        except Exception:
            clients_list = []
        clients_list = [c for c in clients_list if c and c.get("name")]

        if not clients_list:
            st.info("No clients yet. Add one above, or issue a quote — clients auto-record when you issue.")
        else:
            st.markdown(f"**{len(clients_list)} client(s)**")
            for c in clients_list:
                with st.container(border=True):
                    head_cols = st.columns([3, 1])
                    with head_cols[0]:
                        st.markdown(f"### {c.get('name')}")
                        bits = []
                        if c.get("attention"): bits.append(f"📞 {c['attention']}")
                        if c.get("vat_reg"): bits.append(f"VAT: {c['vat_reg']}")
                        if c.get("contact"): bits.append(c["contact"])
                        if bits:
                            st.caption(" · ".join(bits))
                        if c.get("address"): st.caption(c["address"])
                        if c.get("notes"): st.caption(f"📝 {c['notes']}")
                    with head_cols[1]:
                        st.metric("Quotes", c.get("quote_count", 0))
                    actions = st.columns(3)
                    if actions[0].button("Edit", icon=":material/edit:", key=f"adm-cn-edit-{c['name']}", use_container_width=True):
                        ss[f"editing-cn-{c['name']}"] = True
                    if actions[1].button("Use in current quote", key=f"adm-cn-use-{c['name']}", use_container_width=True):
                        h = ss.quote_header
                        h["client_name"] = c.get("name") or ""
                        h["client_vat_reg"] = c.get("vat_reg") or ""
                        h["client_address"] = c.get("address") or ""
                        h["attention"] = c.get("attention") or ""
                        ss.quote_header = h
                        st.toast(f"{c['name']} loaded into current quote header.")
                        st.rerun()
                    if actions[2].button("Delete", icon=":material/delete:", key=f"adm-cn-del-{c['name']}", use_container_width=True):
                        if memory.delete_client(c["name"]):
                            log("admin_delete_client", details={"name": c["name"]})
                            st.toast(f"Deleted {c['name']}")
                            st.rerun()

                    if ss.get(f"editing-cn-{c['name']}"):
                        with st.form(f"edit-cn-form-{c['name']}", clear_on_submit=False):
                            ec1, ec2 = st.columns(2)
                            with ec1:
                                e_vat = st.text_input("VAT reg.", value=c.get("vat_reg") or "")
                                e_addr = st.text_input("Address / site", value=c.get("address") or "")
                            with ec2:
                                e_attn = st.text_input("Attention", value=c.get("attention") or "")
                                e_contact = st.text_input("Contact", value=c.get("contact") or "")
                            e_notes = st.text_area("Notes", value=c.get("notes") or "", height=60)
                            sb1, sb2 = st.columns(2)
                            saved = sb1.form_submit_button("Save changes", icon=":material/save:", type="primary", use_container_width=True)
                            cancelled = sb2.form_submit_button("Cancel", use_container_width=True)
                        if saved:
                            memory.upsert_client(c["name"], e_vat, e_addr, e_attn, e_contact, e_notes)
                            ss.pop(f"editing-cn-{c['name']}", None)
                            st.toast("Saved.")
                            st.rerun()
                        if cancelled:
                            ss.pop(f"editing-cn-{c['name']}", None)
                            st.rerun()

    # ---------------- Projects ----------------
    with sub_projects:
        with st.expander("Add new project", icon=":material/add:", expanded=False):
            np_cols = st.columns(2)
            with np_cols[0]:
                p_name = st.text_input("Project name *", key="adm-pj-name")
                p_client = st.text_input("Primary client", key="adm-pj-client")
            with np_cols[1]:
                p_status = st.selectbox("Status", ["active", "closed", "archived"], key="adm-pj-status")
                p_notes = st.text_area("Notes", height=70, key="adm-pj-notes")
            if st.button("Save project", icon=":material/save:", type="primary", key="adm-pj-save"):
                if not p_name.strip():
                    st.error("Project name is required.")
                else:
                    memory.upsert_project_admin(p_name, p_client, p_notes, p_status)
                    log("admin_add_project", details={"name": p_name})
                    st.success(f"Saved project: {p_name}")
                    st.rerun()

        try:
            projects_list = memory.list_projects_admin() or []
        except Exception:
            projects_list = []
        projects_list = [p for p in projects_list if p and p.get("name")]

        if not projects_list:
            st.info("No projects yet. Add one above, or issue a quote with a project name and it auto-creates.")
        else:
            st.markdown(f"**{len(projects_list)} project(s)**")
            for p in projects_list:
                with st.container(border=True):
                    head_cols = st.columns([3, 1])
                    with head_cols[0]:
                        st.markdown(f"### {p.get('name')}")
                        bits = []
                        if p.get("primary_client"): bits.append(f"👤 {p['primary_client']}")
                        if p.get("status"): bits.append(f"status: **{p['status']}**")
                        if bits: st.caption(" · ".join(bits))
                        if p.get("notes"): st.caption(f"📝 {p['notes']}")
                    actions = st.columns(3)
                    if actions[0].button("Use in current quote", key=f"adm-pj-use-{p['name']}", use_container_width=True):
                        h = ss.quote_header
                        h["project"] = p.get("name") or ""
                        if p.get("primary_client") and not h.get("client_name"):
                            h["client_name"] = p["primary_client"]
                        ss.quote_header = h
                        st.toast(f"Project '{p['name']}' applied to current quote.")
                        st.rerun()
                    if p.get("created_at"):  # admin-managed only
                        if actions[1].button("Edit", icon=":material/edit:", key=f"adm-pj-edit-{p['name']}", use_container_width=True):
                            ss[f"editing-pj-{p['name']}"] = True
                        if actions[2].button("Delete", icon=":material/delete:", key=f"adm-pj-del-{p['name']}", use_container_width=True):
                            if memory.delete_project_admin(p["name"]):
                                log("admin_delete_project", details={"name": p["name"]})
                                st.toast(f"Deleted project {p['name']}")
                                st.rerun()
                    else:
                        actions[1].caption("(auto-inferred from past quote — promote by editing)")
                        if actions[2].button("Promote to managed", icon=":material/push_pin:", key=f"adm-pj-promote-{p['name']}", use_container_width=True):
                            memory.upsert_project_admin(p["name"], p.get("primary_client") or "", p.get("notes") or "", "active")
                            st.toast(f"Promoted '{p['name']}' to managed project")
                            st.rerun()

                    if ss.get(f"editing-pj-{p['name']}"):
                        with st.form(f"edit-pj-form-{p['name']}", clear_on_submit=False):
                            ec1, ec2 = st.columns(2)
                            with ec1:
                                e_client = st.text_input("Primary client", value=p.get("primary_client") or "")
                            with ec2:
                                e_status = st.selectbox("Status", ["active", "closed", "archived"],
                                                        index=["active", "closed", "archived"].index(p.get("status") or "active"))
                            e_notes = st.text_area("Notes", value=p.get("notes") or "", height=60)
                            sb1, sb2 = st.columns(2)
                            saved = sb1.form_submit_button("Save changes", icon=":material/save:", type="primary", use_container_width=True)
                            cancelled = sb2.form_submit_button("Cancel", use_container_width=True)
                        if saved:
                            memory.upsert_project_admin(p["name"], e_client, e_notes, e_status)
                            ss.pop(f"editing-pj-{p['name']}", None)
                            st.toast("Saved.")
                            st.rerun()
                        if cancelled:
                            ss.pop(f"editing-pj-{p['name']}", None)
                            st.rerun()

    # ---------------- Catalog (learned items from past quotes) ----------------
    with sub_catalog:
        # ----- Migration: old projects/ layout → new clients/{C}/{P}/ layout -----
        with st.container(border=True):
            mcols = st.columns([3, 1, 1])
            with mcols[0]:
                st.markdown("**Folder layout migration** *(old `projects/{P}/quotes/{Q}/` → new `clients/{Client}/{Project}/`)*")
                st.caption("Reads each quote's JSON to get the authoritative client + project, "
                           "then renames files to `{Quote No.} — {ISO date} — {scope}.{ext}` and moves them. "
                           "Dry run first to preview.")
            with mcols[1]:
                if st.button("Dry run", icon=":material/search:", use_container_width=True, key="mig-dry"):
                    if not ss.get("work_folder"):
                        st.error("Set a Work folder in the sidebar first.")
                    else:
                        report = _migrate_old_layout(ss.work_folder, dry_run=True)
                        if not report.get("old_root_exists"):
                            st.info("No `projects/` folder under work folder — nothing to migrate.")
                        else:
                            st.success(f"Would move {report['moved']} file(s); skip {report['skipped']}; errors {len(report['errors'])}")
                            if report.get("examples"):
                                st.markdown("**Sample renames:**")
                                for src_name, dst_name in report["examples"]:
                                    st.markdown(f"- `{src_name}` → `{dst_name}`")
            with mcols[2]:
                if st.button("Migrate", icon=":material/forward:", use_container_width=True, type="primary", key="mig-go"):
                    if not ss.get("work_folder"):
                        st.error("Set a Work folder in the sidebar first.")
                    else:
                        report = _migrate_old_layout(ss.work_folder, dry_run=False)
                        log("layout_migration", details=report)
                        st.success(f"Migrated {report['moved']} file(s) into `clients/{{Client}}/{{Project}}/` layout")
                        if report.get("errors"):
                            st.error(f"{len(report['errors'])} error(s):")
                            for e in report["errors"][:5]:
                                st.markdown(f"- {e}")
                        st.rerun()

        # Backfill + Backup banner
        with st.container(border=True):
            bcols = st.columns([2, 1, 1])
            with bcols[0]:
                st.markdown("**Backfill from past quotes**")
                st.caption("Sweep every line item from `issued_quote_items` into the catalog (catches items missed before the learning hook was wired).")
            with bcols[1]:
                if st.button("Backfill catalog", icon=":material/sync:", use_container_width=True, type="primary"):
                    n = memory.backfill_learned_items_from_quotes()
                    log("backfill_catalog", details={"items_processed": n})
                    st.toast(f"Backfilled {n} item(s) from past quotes", icon="✅")
                    st.rerun()
            with bcols[2]:
                # DB backup — copy memory.sqlite into the work folder with a timestamp
                if st.button("Backup DB", icon=":material/save:", use_container_width=True,
                             help="Copies the SQLite database to {work_folder}/backups/ with a timestamp"):
                    try:
                        import shutil
                        from datetime import datetime as _dt
                        src = Path(__file__).parent / "data" / "memory.sqlite"
                        if not src.exists():
                            st.warning("No database file to back up yet.")
                        else:
                            wf = (ss.get("work_folder") or "").strip() or str(Path(__file__).parent / "data")
                            target_dir = Path(wf) / "backups"
                            target_dir.mkdir(parents=True, exist_ok=True)
                            stamp = _dt.utcnow().strftime("%Y%m%d-%H%M%S")
                            dst = target_dir / f"memory-{stamp}.sqlite"
                            shutil.copy2(src, dst)
                            st.success(f"Backed up to {dst}")
                            log("db_backup", details={"path": str(dst), "size": dst.stat().st_size})
                    except Exception as e:
                        st.error(f"Backup failed: {e}")

        try:
            cat_items = memory.list_learned_items() or []
        except Exception:
            cat_items = []
        cat_items = [i for i in cat_items if i and i.get("description")]

        # Filter
        fcol_a, fcol_b, fcol_c = st.columns([1, 1, 2])
        trades_in_cat = sorted({i.get("trade") for i in cat_items if i.get("trade")})
        with fcol_a:
            cat_trade = st.selectbox("Trade", ["(all)"] + trades_in_cat, key="cat-filter-trade")
        with fcol_b:
            cat_search = st.text_input("Search", key="cat-filter-search", placeholder="description")
        with fcol_c:
            st.metric("Catalog size", f"{len(cat_items)} item(s)")

        filtered = cat_items
        if cat_trade != "(all)":
            filtered = [i for i in filtered if i.get("trade") == cat_trade]
        if cat_search.strip():
            q = cat_search.strip().lower()
            filtered = [i for i in filtered if q in (i.get("description") or "").lower()
                        or q in (i.get("subcategory") or "").lower()]

        if not filtered:
            st.info("Nothing in the catalog matches. Try **Backfill** above, or issue a quote with new items.")
        else:
            for i in filtered:
                desc = i.get("description") or ""
                norm = desc.lower()
                trade = i.get("trade") or "other"
                sub = i.get("subcategory") or ""
                unit = i.get("unit") or "no"
                med = i.get("median_rate")
                freq = i.get("frequency") or 0
                with st.container(border=True):
                    head = st.columns([3, 1, 1])
                    with head[0]:
                        st.markdown(f"**{desc}**")
                        bits = [f"`{trade}`"]
                        if sub:
                            bits.append(f"› **{sub}**")
                        bits.append(f"unit `{unit}`")
                        bits.append(f"used **{freq}×**")
                        st.caption(" · ".join(bits))
                    with head[1]:
                        st.metric("Rate", f"R {(med or 0):,.2f}" if med else "—")
                    with head[2]:
                        if st.button("", icon=":material/delete:", key=f"cat-del-{norm[:60]}", help="Remove from catalog"):
                            memory.delete_learned_item(norm)
                            log("delete_learned_item", details={"description": desc})
                            st.rerun()
                    edit_cols = st.columns([2, 2, 1])
                    with edit_cols[0]:
                        new_sub = st.text_input("Sub-category", value=sub,
                                                key=f"cat-sub-{norm[:60]}",
                                                label_visibility="collapsed",
                                                placeholder="Sub-category (e.g. Doors)")
                    with edit_cols[1]:
                        new_rate = st.number_input("New rate", value=float(med or 0.0), min_value=0.0, step=10.0,
                                                   key=f"cat-rate-{norm[:60]}",
                                                   label_visibility="collapsed")
                    with edit_cols[2]:
                        if st.button("Save", icon=":material/save:", key=f"cat-save-{norm[:60]}", use_container_width=True):
                            changed = False
                            if new_sub != sub:
                                memory.update_learned_item_subcategory(norm, new_sub)
                                changed = True
                            if abs(float(new_rate) - float(med or 0)) > 0.01:
                                memory.update_learned_item_rate(norm, float(new_rate))
                                changed = True
                            if changed:
                                log("edit_learned_item", details={"description": desc})
                                st.toast("Saved", icon="✅")
                                st.rerun()


# ============================================================================
# TAB 4 — RATE REVIEW QUEUE
# ============================================================================

with tab_rates:
    # ----- Rate review export (send to Robert) -----
    with st.container(border=True):
        st.subheader("📋 Send all rates to Robert for review")
        st.caption(
            "One-click export of every rate currently in use — catalogue + learned items from past quotes. "
            "Robert fills the empty 'says' column with corrections, you re-import, the catalogue updates."
        )
        cols = st.columns([2, 2, 2])
        with cols[0]:
            reviewer_name = st.text_input("Reviewer name", value="Robert", key="rate-reviewer-name")
        with cols[1]:
            company_name = st.text_input("Company on report", value=ss.quote_header.get("company_name") or "Ndlovu T Projects (Pty) Ltd", key="rate-company")

        try:
            from rate_review_export import build_rate_review_xlsx
            xlsx_bytes = build_rate_review_xlsx(
                catalogue=load_rates(),
                learned=memory.list_learned_items(),
                company_name=company_name,
                reviewer_name=reviewer_name,
            )
        except Exception as e:
            xlsx_bytes = b""
            st.error(f"Couldn't build export: {e}")

        action_cols = st.columns([1, 1])
        with action_cols[0]:
            if xlsx_bytes:
                stamp = datetime.utcnow().strftime("%Y-%m-%d")
                st.download_button(
                    f"⬇️ Download rates-for-{reviewer_name.lower()}-{stamp}.xlsx",
                    data=xlsx_bytes,
                    file_name=f"rates-for-{_safe_filename(reviewer_name).lower()}-{stamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )
        with action_cols[1]:
            if xlsx_bytes and ss.get("work_folder"):
                if st.button(f"Save to work folder ({ss.work_folder}\\reviews\\)", icon=":material/save:",
                             use_container_width=True, key="save-review-btn"):
                    try:
                        target = Path(ss.work_folder) / "reviews"
                        target.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.utcnow().strftime("%Y-%m-%d")
                        path = target / f"rates-for-{_safe_filename(reviewer_name).lower()}-{stamp}.xlsx"
                        path.write_bytes(xlsx_bytes)
                        st.success(f"Saved to {path}")
                        log("rate_review_saved", details={"path": str(path), "reviewer": reviewer_name})
                    except Exception as e:
                        st.error(f"Save failed: {e}")

    st.divider()

    st.subheader("Rates needing attention")
    st.caption(f"Two flags: rates older than {rate_review.STALE_DAYS} days, and rates the learner sees being adjusted ≥ ±{int(learner.DRIFT_THRESHOLD_PCT*100)}% on average across {learner.DRIFT_MIN_SAMPLES}+ recent quotes.")

    queue = rate_review.review_queue()
    if not queue:
        st.success(f"No rates flagged. Catalogue is fresh and the learner has not detected systematic drift.")
    else:
        for entry in queue:
            with st.container(border=True):
                cols = st.columns([2.5, 1, 1, 1, 1.5, 1.2])
                with cols[0]:
                    st.markdown(f"**{entry['code']}** — {entry['description']}")
                    flags = []
                    if entry["stale"]:
                        flags.append(f"🕒 {entry['age_days']}d old")
                    if entry["drift_pct"] is not None:
                        flags.append(f"📈 drift {entry['drift_pct']*100:+.1f}% across {entry['drift_samples']} edits")
                    st.caption(" · ".join(flags))
                cols[1].write(entry["trade"])
                cols[2].write(entry["unit"])
                cols[3].markdown(f"R {entry['rate_zar']:,.2f}")
                with cols[4]:
                    new_val = st.number_input(
                        "new", value=float(entry["rate_zar"]), step=10.0,
                        key=f"newrate-{entry['code']}", label_visibility="collapsed",
                    )
                    if entry["drift_pct"] is not None:
                        suggested = round(entry["rate_zar"] * (1 + entry["drift_pct"]), 2)
                        st.caption(f"Suggested: R {suggested:,.2f}")
                with cols[5]:
                    if st.button("Save", icon=":material/save:", key=f"saverate-{entry['code']}"):
                        if rate_review.apply_one_uplift(entry["code"], new_val):
                            log("rate_uplift", details={"code": entry["code"], "old": entry["rate_zar"], "new": new_val})
                            st.success(f"Updated {entry['code']}")
                            st.rerun()

    st.divider()
    st.subheader("Bulk uplift")
    st.caption("Apply a percentage uplift to all rates in a trade. Optionally restricted to rates older than 90 days.")

    bcol1, bcol2, bcol3, bcol4 = st.columns([1.5, 1, 1, 1])
    with bcol1:
        all_trades = sorted({r.trade for r in load_rates()})
        bulk_trade = st.selectbox("Trade", ["(all)"] + all_trades, key="bulk-trade")
    with bcol2:
        bulk_pct = st.number_input("Uplift %", value=5.0, step=1.0, key="bulk-pct")
    with bcol3:
        only_stale = st.checkbox("Only stale (>90d)", value=True, key="bulk-stale")
    with bcol4:
        if st.button("Apply uplift", icon=":material/trending_up:", key="bulk-apply"):
            n = rate_review.apply_bulk_uplift(
                trade=None if bulk_trade == "(all)" else bulk_trade,
                pct=bulk_pct / 100.0,
                only_stale=only_stale,
            )
            log("bulk_uplift", details={"trade": bulk_trade, "pct": bulk_pct, "only_stale": only_stale, "updated": n})
            st.success(f"Updated {n} rate(s).")
            st.rerun()

# ============================================================================
# TAB 3 — AUDIT LOG
# ============================================================================

with tab_audit:
    from ui import tab_audit as _tab_audit_module
    _tab_audit_module.render(ss)


# Floating scroll-to-top — desktop only
st.markdown(
    '<a class="qs-totop" href="#qs-top" title="Back to top">↑</a>',
    unsafe_allow_html=True,
)
