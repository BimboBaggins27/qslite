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

import demo_extractor
import key_manager
import learner
import memory
import rate_review
import validators
import versioning
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

try:
    from voice_edits import parse_voice_instruction, apply_edits as _apply_voice_edits
except Exception:
    parse_voice_instruction = None
    _apply_voice_edits = None


st.set_page_config(
    page_title="QS Live — Quotation Studio",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
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

# ---------- visual polish ----------
LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
LOGO_PATH.parent.mkdir(parents=True, exist_ok=True)
if LOGO_PATH.exists():
    try:
        st.logo(str(LOGO_PATH))
    except Exception:
        pass

st.markdown(
    """
    <style>
    /* Fonts */
    html, body, [class*="css"]  {
        font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
        -webkit-font-smoothing: antialiased;
    }
    h1, h2, h3 { letter-spacing: -0.01em; }
    h1 { font-weight: 700 !important; }

    /* Hero header */
    .qs-hero {
        background: linear-gradient(135deg, #0A2540 0%, #13B5EA 110%);
        color: #fff;
        padding: 18px 26px;
        border-radius: 14px;
        margin-bottom: 22px;
        box-shadow: 0 8px 28px rgba(10,37,64,0.18);
    }
    .qs-hero h1 { color: #fff; font-size: 1.55rem; margin: 0; font-weight: 700; letter-spacing: -0.02em; }
    .qs-hero p  { color: #E5F4FB; margin: 4px 0 0 0; font-size: 0.95rem; opacity: 0.92; }

    /* Containers */
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px !important;
        border-color: rgba(120,140,160,0.18) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }

    /* Buttons */
    .stButton > button {
        border-radius: 10px !important;
        font-weight: 500;
        transition: transform 0.05s ease, box-shadow 0.15s ease;
    }
    .stButton > button:hover { transform: translateY(-1px); }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #13B5EA 0%, #0A8CC0 100%) !important;
        border: 0 !important;
        box-shadow: 0 2px 8px rgba(19,181,234,0.35);
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: #0A2540;
    }
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: #EAF1F8 !important; }
    [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        color: #98AABE !important;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        border-bottom: 1px solid rgba(120,140,160,0.16);
    }
    .stTabs [data-baseweb="tab"] {
        font-weight: 500;
        padding: 12px 16px;
        border-radius: 8px 8px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(19,181,234,0.08);
        color: #0A2540 !important;
    }

    /* Metrics */
    [data-testid="stMetric"] {
        background: rgba(244,248,250,0.6);
        padding: 10px 14px;
        border-radius: 10px;
        border: 1px solid rgba(120,140,160,0.10);
    }
    [data-testid="stMetricLabel"] { font-size: 0.78rem !important; opacity: 0.7; }
    [data-testid="stMetricValue"] { font-size: 1.15rem !important; font-weight: 600 !important; }

    /* Inputs */
    .stTextInput input, .stTextArea textarea, .stNumberInput input {
        border-radius: 8px !important;
    }

    /* Reduce default top padding */
    .block-container { padding-top: 1.2rem !important; }

    /* ---------- Dropdown / selectbox readability ---------- */
    /* The closed selectbox itself */
    [data-baseweb="select"] > div {
        background: #FFFFFF !important;
        color: #0A2540 !important;
        border-radius: 8px !important;
        border-color: rgba(120,140,160,0.30) !important;
        min-height: 38px;
    }
    [data-baseweb="select"] svg { color: #5C6B73; }

    /* The popover that opens with the options list */
    [data-baseweb="popover"] {
        background: #FFFFFF !important;
        border-radius: 10px !important;
        box-shadow: 0 8px 24px rgba(10,37,64,0.18) !important;
        max-width: min(100%, 720px) !important;
    }
    [data-baseweb="popover"] [role="listbox"] {
        background: #FFFFFF !important;
        max-height: 65vh !important;
        padding: 4px !important;
    }
    [data-baseweb="popover"] [role="option"] {
        font-size: 14px !important;
        line-height: 1.45 !important;
        padding: 10px 14px !important;
        white-space: normal !important;       /* wrap long lines instead of truncating */
        word-break: break-word !important;
        color: #0A2540 !important;
        background: #FFFFFF !important;
        border-bottom: 1px solid rgba(120,140,160,0.10) !important;
        border-radius: 6px;
    }
    [data-baseweb="popover"] [role="option"]:last-child { border-bottom: none !important; }
    [data-baseweb="popover"] [role="option"]:hover {
        background: rgba(19,181,234,0.12) !important;
        color: #0A2540 !important;
    }
    [data-baseweb="popover"] [role="option"][aria-selected="true"] {
        background: rgba(19,181,234,0.20) !important;
        color: #0A2540 !important;
        font-weight: 600 !important;
    }
    /* Search input inside dropdown (selectbox with type-to-filter) */
    [data-baseweb="popover"] input {
        font-size: 14px !important;
        color: #0A2540 !important;
        background: #F4F8FA !important;
    }

    /* Same treatment for multiselect */
    [data-baseweb="tag"] {
        background: rgba(19,181,234,0.16) !important;
        color: #0A2540 !important;
        border-radius: 6px !important;
    }

    /* ---------- Ruflo-inspired design system ---------- */
    .qs-card {
        background: #fff;
        border: 1px solid rgba(120,140,160,0.16);
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(10,37,64,0.04);
        transition: transform 0.06s ease, box-shadow 0.15s ease;
    }
    .qs-card:hover { box-shadow: 0 4px 12px rgba(10,37,64,0.08); }
    .qs-card-head {
        display: flex; justify-content: space-between; align-items: baseline;
        gap: 8px; margin-bottom: 4px;
    }
    .qs-card-title { font-weight: 600; color: #0A2540; font-size: 1.0rem; }
    .qs-card-meta  { color: #5C6B73; font-size: 0.82rem; }
    .qs-card-foot  { color: #5C6B73; font-size: 0.78rem; margin-top: 6px; }

    .qs-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.74rem;
        font-weight: 500;
        line-height: 1.4;
    }
    .qs-pill-green   { background: rgba(34,197,94,0.12);  color: #15803D; }
    .qs-pill-amber   { background: rgba(245,158,11,0.14); color: #B45309; }
    .qs-pill-red     { background: rgba(239,68,68,0.12);  color: #B91C1C; }
    .qs-pill-info    { background: rgba(19,181,234,0.12); color: #0A8CC0; }
    .qs-pill-grey    { background: rgba(120,140,160,0.14); color: #5C6B73; }

    .qs-strip {
        display: flex; flex-wrap: wrap; gap: 10px;
        background: rgba(244,248,250,0.7);
        border: 1px solid rgba(120,140,160,0.10);
        border-radius: 10px;
        padding: 8px 12px;
        margin-bottom: 10px;
        font-size: 0.85rem;
    }
    .qs-strip-cell {
        display: flex; align-items: center; gap: 6px;
        padding-right: 14px;
        border-right: 1px solid rgba(120,140,160,0.18);
    }
    .qs-strip-cell:last-child { border-right: none; }
    .qs-strip-label { color: #5C6B73; font-size: 0.75rem; }
    .qs-strip-value { font-weight: 600; color: #0A2540; }

    /* ---------- Mobile (< 768px) ---------- */
    @media (max-width: 768px) {
        .qs-hero { padding: 14px 16px; border-radius: 10px; }
        .qs-hero h1 { font-size: 1.1rem; }
        .qs-hero p  { font-size: 0.85rem; }

        /* Stack columns instead of side-by-side */
        [data-testid="column"] { width: 100% !important; flex: 0 0 100% !important; }

        /* Bigger touch targets */
        .stButton > button {
            min-height: 44px;
            font-size: 0.95rem;
        }
        .stTextInput input, .stTextArea textarea, .stNumberInput input {
            font-size: 16px !important;  /* prevents iOS zoom-on-focus */
            min-height: 40px;
        }
        .stSelectbox [data-baseweb="select"] > div { min-height: 40px; }

        /* Tighter padding for content */
        .block-container { padding-top: 0.6rem !important; padding-left: 0.5rem; padding-right: 0.5rem; }

        /* Tabs scroll horizontally on small screens */
        .stTabs [data-baseweb="tab-list"] {
            overflow-x: auto;
            flex-wrap: nowrap;
        }
        .stTabs [data-baseweb="tab"] { white-space: nowrap; padding: 10px 12px; }

        /* Metrics: 1 per row, smaller */
        [data-testid="stMetric"] { padding: 6px 10px; }
        [data-testid="stMetricValue"] { font-size: 1rem !important; }

        /* Hide brand image on tiny screens to save space */
        .qs-hero img { display: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
    if key_manager.has_api_key():
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


def _autosave_to_work_folder(quote_payload: dict) -> Optional[str]:
    """Save issued PDF + Excel + JSON under {work_folder}/projects/{project}/quotes/{quote_no}/.
    A client may have many projects, so structure is project-first, quote-no-second.
    Falls back to '_unfiled' when no project name is set."""
    folder = (ss.get("work_folder") or "").strip()
    if not folder:
        return None
    try:
        from excel import issued_quote_to_xlsx
        from pdf_render import render_quote_pdf

        header = quote_payload.get("header") or {}
        project = _safe_filename(header.get("project") or "_unfiled", "_unfiled")
        client = _safe_filename(header.get("client_name") or "client", "client")
        quote_no = _safe_filename(header.get("quote_no") or quote_payload.get("memory_id") or "quote")
        target_dir = Path(folder) / "projects" / project / "quotes" / quote_no
        target_dir.mkdir(parents=True, exist_ok=True)
        base = f"{quote_no} — {client}"
        (target_dir / f"{base}.pdf").write_bytes(render_quote_pdf(quote_payload))
        (target_dir / f"{base}.xlsx").write_bytes(issued_quote_to_xlsx(quote_payload))
        (target_dir / f"{base}.json").write_text(
            json.dumps(quote_payload, indent=2, default=str), encoding="utf-8"
        )
        ss["last_saved_dir"] = str(target_dir)
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

    if not key_manager.has_api_key():
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

DEMO_MODE = not key_manager.has_api_key()

if DEMO_MODE:
    st.warning(
        "🧪  **DEMO MODE** — no Anthropic API key set, so extractions return deterministic synthetic data marked `[DEMO]`. "
        "Every other feature works (review, edit, learner, locks, Excel export). Add a key in the sidebar to enable real vision extraction."
    )

# Hero header with brand mark
hero_left, hero_right = st.columns([3, 2])
with hero_left:
    if LOGO_PATH.exists():
        col_logo, col_title = st.columns([1, 4])
        with col_logo:
            st.image(str(LOGO_PATH), width=88)
        with col_title:
            st.markdown(
                """
                <div class="qs-hero">
                  <h1>QS Live · Quotation Studio</h1>
                  <p>Drop drawings, photos or PDFs in. The AI builds your quotation. You polish, label, and issue.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            """
            <div class="qs-hero">
              <h1>QS Live · Quotation Studio</h1>
              <p>Drop drawings, photos or PDFs in. The AI builds your quotation. You polish, label, and issue.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

with hero_right:
    metrics_a, metrics_b, metrics_c = st.columns(3)
    stats = memory.summary_stats()
    learned = stats["rate_edits"] + stats["qty_edits"]
    queue = rate_review.review_queue()
    with metrics_a:
        st.metric("Learner memory", f"{learned} edits", help=f"{stats['issued_quotes']} quote(s) issued · model is learning your overrides")
    with metrics_b:
        st.metric("Rates flagged", f"{len(queue)}" if queue else "0", help="Stale or drifting rates")
    with metrics_c:
        if ss.line_items:
            st.metric("Running total", f"R {quote_total(ss.line_items):,.0f}")
        else:
            st.metric("Running total", "—")

# ---------- sidebar: undo + zone locks ----------

with st.sidebar:
    st.subheader("Anthropic API key")
    if key_manager.has_api_key():
        masked = key_manager.get_api_key()
        st.success(f"✓ Key set ({masked[:10]}…{masked[-4:]}, {len(masked)} chars)")
        if st.button("Change / clear key", use_container_width=True):
            ss.show_key_input = True
            ss.key_input_seq += 1  # rotate widget key → fresh empty input
            st.rerun()
    else:
        st.info("Paste your key below. Saved to qs-app/.env so you only do this once.")
        ss.show_key_input = True

    if ss.get("show_key_input"):
        widget_key = f"key-input-{ss.key_input_seq}"
        typed = st.text_input(
            "API key — paste, verify, then click Save",
            key=widget_key,
            placeholder="",
            help="Get one at console.anthropic.com → API keys. Starts with sk-ant-…",
        )
        stripped = (typed or "").strip()
        if stripped:
            preview = f"{stripped[:10]}…{stripped[-4:]}" if len(stripped) > 14 else stripped
            if stripped.startswith("sk-ant-"):
                st.caption(f"✓ Looks valid · {len(stripped)} chars · {preview}")
            else:
                st.caption(f"⚠ Doesn't start with `sk-ant-` (got `{preview}`, {len(stripped)} chars). Save anyway?")
        else:
            st.caption("👆 Paste your key into the field above.")

        col_save, col_clear = st.columns(2)
        save_clicked = col_save.button("💾 Save", type="primary", use_container_width=True, key=f"save-{ss.key_input_seq}")
        clear_clicked = col_clear.button("✕ Clear stored key", use_container_width=True, key=f"clear-{ss.key_input_seq}")

        if save_clicked:
            if not stripped:
                st.error("The field is empty. Paste your key first, then click Save.")
            else:
                key_manager.save_api_key(stripped)
                ss.show_key_input = False
                ss.key_input_seq += 1
                log("save_api_key", details={"length": len(stripped)})
                st.toast("✓ API key saved", icon="✅")
                st.rerun()
        if clear_clicked:
            key_manager.clear_api_key()
            ss.show_key_input = True
            ss.key_input_seq += 1
            log("clear_api_key")
            st.rerun()

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
    if st.button("🆕 New job (reset client + scope)", use_container_width=True,
                 help="Clears client name, quote no., RE: subject, line items, and pending review. Keeps your company info, banking, payment terms, and learner memory."):
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
        if st.button(f"↶ Undo: {last}", use_container_width=True):
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

tab_quote, tab_past, tab_admin, tab_rates, tab_audit = st.tabs(
    ["📐 Quote builder", "📁 Past quotes", "📇 Clients & Projects", "💰 Rate review queue", "📜 Audit log"]
)

# ============================================================================
# TAB 1 — QUOTE BUILDER
# ============================================================================

with tab_quote:

    # ===== CURRENT QUOTE SUMMARY STRIP =====
    # Always-visible banner at top of Quote Builder so you can see the current job's identity at a glance
    # Auto-suggest a Quote No. if blank
    h = ss.quote_header
    if not (h.get("quote_no") or "").strip():
        try:
            h["quote_no"] = memory.suggest_next_quote_no("NPQ")
            ss.quote_header = h
        except Exception:
            pass
    qno = (h.get("quote_no") or "—").strip() or "—"
    client = (h.get("client_name") or "").strip() or "no client"
    project = (h.get("project") or "").strip() or "no project"
    sow = (h.get("re_subject") or "").strip() or "(scope not set — drop inputs and run)"
    # Color the missing fields red
    qno_html = f'<span class="qs-strip-value">{qno}</span>'
    client_html = f'<span class="qs-strip-value">{client}</span>' if h.get("client_name") else f'<span class="qs-strip-value" style="color:#B91C1C">⚠ no client</span>'
    project_html = f'<span class="qs-strip-value">{project}</span>' if h.get("project") else f'<span class="qs-strip-value" style="color:#B91C1C">⚠ no project</span>'
    sow_html = f'<span class="qs-strip-value">"{sow}"</span>'
    st.markdown(
        f'<div class="qs-strip" style="margin-bottom:14px;">'
        f'<div class="qs-strip-cell"><span class="qs-strip-label">Quote no.</span> {qno_html}</div>'
        f'<div class="qs-strip-cell"><span class="qs-strip-label">Client</span> {client_html}</div>'
        f'<div class="qs-strip-cell"><span class="qs-strip-label">Project</span> {project_html}</div>'
        f'<div class="qs-strip-cell" style="border-right:none"><span class="qs-strip-label">RE</span> {sow_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ----- Quote header (editable cover-page fields) -----
    with st.expander("📝 Quote header (editable — company, client, quote no, terms)", expanded=False):
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
                    if st.button("💾 Save & use", key="hd-newclient-save", type="primary", use_container_width=True):
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
                    if st.button("💾 Save & use", key="hd-newproject-save", type="primary", use_container_width=True):
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

    # ----- Inbox folder watcher — drop files in E:\NdlovuQS\inbox\ and click Process -----
    inbox_files = _list_inbox_files()
    # Collapsed by default; expand if there are files waiting
    with st.expander(f"📥 Inbox ({len(inbox_files)} file(s) ready)" if inbox_files else "📥 Inbox", expanded=bool(inbox_files)):
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
                "🚀 Process inbox", type="primary", use_container_width=True,
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

    # ----- Site Survey (foreman template upload) -----
    with st.expander("📋 Site Survey — download blank template / import filled-in survey", expanded=False):
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

    # ----- Single input channel — AI decides what to do -----
    with st.container(border=True):
        st.subheader("1. Drop anything in — the AI decides what to do")
        st.caption(
            "Photos, drawings, plans, PDFs — one or many. The AI figures out whether it's a single take-off, "
            "a comparison between drawings, or something else. If it's stuck, it asks you instead of failing."
        )
        uploads = st.file_uploader(
            " ",
            type=["png", "jpg", "jpeg", "webp", "pdf"],
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
                    label="📋 Paste image",
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
            "Run", type="primary",
            disabled=not uploads or ss.frozen_quote is not None,
            use_container_width=True,
        )

        if run and uploads:
            # Stash bytes on session state so we can re-call after a clarification answer.
            stashed = []
            for up in uploads:
                is_pdf = (up.type == "application/pdf") or up.name.lower().endswith(".pdf")
                raw_bytes = up.getvalue()
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

            ss.unified_inputs = stashed
            ss.unified_context = extra_context or ""
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
            if st.button("✓ Apply selected", type="primary", use_container_width=True):
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
            if st.button("✕ Discard pending", use_container_width=True):
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
            if cols[1].button(f"✓ Confirm all ({len(pending)})", type="primary", use_container_width=True, key="confirm-all"):
                take_snapshot(f"confirm all ({len(pending)} items)")
                for li in pending:
                    li.state = EditState.USER_CONFIRMED
                log("confirm_all", details={"count": len(pending)})
                st.rerun()
            if cols[2].button("✓ Confirm green-band only", use_container_width=True,
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
                    if zb[1].button(f"✓ Confirm zone ({len(zone_pending)})", key=f"confirm-zone-{zone}", use_container_width=True):
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
                            if st.button("✓ Confirm", key=f"confirm-{li.id}"):
                                take_snapshot(f"confirm {li.description[:30]}")
                                li.state = EditState.USER_CONFIRMED
                                log("confirm_item", li.id)
                                st.rerun()

                    with c[7]:
                        if st.button("✕", key=f"del-{li.id}", help="Remove line item"):
                            items_to_remove.append(li.id)

        if items_to_remove:
            take_snapshot(f"remove {len(items_to_remove)} item(s)")
            for rid in items_to_remove:
                log("remove_item", rid)
            ss.line_items = [i for i in ss.line_items if i.id not in items_to_remove]
            st.rerun()

        # ----- Manual add -----
        with st.expander("➕ Add manual line item"):
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
                    options = ["— none —"] + [
                        f"[{li['trade']}{' > ' + li['subcategory'] if li.get('subcategory') else ''}] "
                        f"{li['description'][:60]} · R {li['median_rate']:.0f}/{li['unit']} · {li['frequency']}×"
                        for li in filtered
                    ]
                    pick_li = st.selectbox("Item", options=options, key="learned-item-pick")
                if pick_li != "— none —" and st.button("Add this learned item", key="learned-add"):
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
                if st.button("Add", key="manual-add"):
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
                        if cols[5].button("➕ Add", key=f"add-{s['id']}-{sug.get('rate_code') or 'norate'}-{sug_idx}"):
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
            with st.expander("🎙 Verbal edit before issue", expanded=voice_default_open):
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
                    if not key_manager.has_api_key():
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
                    if apply_cols[0].button("✓ Apply edits", type="primary", use_container_width=True, key=f"voice-apply-{ss.voice_seq}"):
                        take_snapshot(f"voice edit: {pe.get('summary', 'verbal')[:40]}")
                        ss.line_items, ss.quote_header, applied_log = _apply_voice_edits(
                            ss.line_items, ss.quote_header, pe["edits"]
                        )
                        ss.voice_edit_pending = None
                        ss.voice_seq += 1
                        log("voice_edit_applied", details={"summary": pe.get("summary", ""), "applied": applied_log})
                        st.toast(f"Applied {len(applied_log)} change(s)", icon="✅")
                        st.rerun()
                    if apply_cols[1].button("✕ Discard", use_container_width=True, key=f"voice-discard-{ss.voice_seq}"):
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
                stamp = ss.frozen_quote["issued_at"].replace(":", "-")
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
                            "📄 Download PDF",
                            data=pdf_bytes,
                            file_name=f"quote-{stamp}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True,
                        )
                with d2:
                    st.download_button(
                        "📊 Download Excel",
                        data=xlsx_bytes,
                        file_name=f"quote-{stamp}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

                if pdf_bytes:
                    with st.expander("📄 Preview PDF (in-app)", expanded=True):
                        try:
                            pages_png = pdf_pages_to_pngs(pdf_bytes, scale=1.5)
                            if len(pages_png) > 1:
                                st.caption(f"Showing all {len(pages_png)} pages.")
                            for label, png in pages_png:
                                st.image(png, caption=label, use_container_width=True)
                        except Exception as e:
                            st.warning(f"Could not render PDF preview inline: {e}")

                with st.expander("Also download as JSON"):
                    st.download_button(
                        "Download JSON snapshot",
                        data=json.dumps(ss.frozen_quote, indent=2, default=str),
                        file_name=f"quote-{stamp}.json",
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

                issue_btn = st.button("📄 Issue Quote (strict, reviewed)", type="primary",
                                      disabled=(not ok) or hard_block)
                quick_btn = st.button(
                    "🚀 Quick Excel (skip review)",
                    help="Bypass per-item review and immediately generate the Excel/PDF from whatever AI extracted. Use when you plan to edit the Excel yourself.",
                    disabled=(not ss.line_items) or hard_block,
                    use_container_width=True,
                )
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

    fcol1, fcol2 = st.columns([3, 2])
    with fcol1:
        search_term = st.text_input("Search (client / project / quote no. / subject / labels)",
                                    value="", key="past-search", placeholder="e.g. ATESS, drywall, NPQ")
    with fcol2:
        try:
            _proj_rows = memory.list_projects() or []
        except Exception:
            _proj_rows = []
        all_projects = sorted({p.get("project") for p in _proj_rows if p.get("project") and p.get("project") != "(no project)"})
        project_filter = st.selectbox("Project", ["(all)"] + all_projects + ["(no project)"], key="past-project")

    project_arg = None if project_filter == "(all)" else (None if project_filter == "(no project)" else project_filter)
    quotes = memory.list_quotes(
        project=project_arg,
        search=search_term.strip() or None,
    )
    # Extra filter for "(no project)"
    if project_filter == "(no project)":
        quotes = [q for q in quotes if not q["project"]]

    if not quotes:
        st.info("No issued quotes match. Issue a quote from the Quote builder tab to see it here.")
    else:
        # Group by project
        by_project: dict[str, list] = {}
        for q in quotes:
            key = q["project"] or "(no project)"
            by_project.setdefault(key, []).append(q)

        for project_name in sorted(by_project.keys()):
            group = by_project[project_name]
            project_total = sum((q["total_zar"] or 0) for q in group)
            with st.expander(
                f"📁 **{project_name}** — {len(group)} quote(s) · R {project_total:,.2f} total",
                expanded=True,
            ):
                for q in group:
                    st.markdown(_quote_card(dict(q)), unsafe_allow_html=True)
                    bcols = st.columns([1, 1, 1, 2])
                    with bcols[0]:
                        if st.button("👁 View", key=f"view-{q['id']}", use_container_width=True):
                            if _load_past_quote_into_workspace(q["id"], mode="view"):
                                st.toast("Loaded as read-only — switch to Quote builder tab to download.")
                                st.rerun()
                    with bcols[1]:
                        if st.button("✏️ Open as draft", key=f"draft-{q['id']}", use_container_width=True,
                                     help="Pull items into a fresh editable draft. Client/quote info reset."):
                            if _load_past_quote_into_workspace(q["id"], mode="draft"):
                                st.toast("Opened as a draft — switch to Quote builder tab.")
                                st.rerun()
                    with bcols[2]:
                        if st.button("🔁 New variation", key=f"var-{q['id']}", use_container_width=True,
                                     help="Clone items AND client info; fresh quote no. and date. Links to parent."):
                            if _load_past_quote_into_workspace(q["id"], mode="variation"):
                                st.toast("Opened as a variation — same client, same project, fresh quote.")
                                st.rerun()


# ============================================================================
# TAB 3 — CLIENTS & PROJECTS (manage the database explicitly)
# ============================================================================

with tab_admin:
    st.subheader("📇 Clients & Projects")
    st.caption("Add, edit, delete clients and projects. The system also auto-creates entries when you issue a quote, but you can manage them here directly.")

    sub_clients, sub_projects, sub_catalog = st.tabs(["👤 Clients", "📁 Projects", "📚 Catalog"])

    # ---------------- Clients ----------------
    with sub_clients:
        with st.expander("➕ Add new client", expanded=False):
            ac_cols = st.columns(2)
            with ac_cols[0]:
                new_name = st.text_input("Client name *", key="adm-cn-name")
                new_vat = st.text_input("VAT reg.", key="adm-cn-vat")
                new_address = st.text_input("Address / site", key="adm-cn-addr")
            with ac_cols[1]:
                new_attn = st.text_input("Attention (contact name)", key="adm-cn-attn")
                new_contact = st.text_input("Contact (phone / email)", key="adm-cn-contact")
                new_notes = st.text_area("Notes", height=70, key="adm-cn-notes")
            if st.button("💾 Save client", type="primary", key="adm-cn-save"):
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
                    if actions[0].button("✏️ Edit", key=f"adm-cn-edit-{c['name']}", use_container_width=True):
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
                    if actions[2].button("🗑 Delete", key=f"adm-cn-del-{c['name']}", use_container_width=True):
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
                            saved = sb1.form_submit_button("💾 Save changes", type="primary", use_container_width=True)
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
        with st.expander("➕ Add new project", expanded=False):
            np_cols = st.columns(2)
            with np_cols[0]:
                p_name = st.text_input("Project name *", key="adm-pj-name")
                p_client = st.text_input("Primary client", key="adm-pj-client")
            with np_cols[1]:
                p_status = st.selectbox("Status", ["active", "closed", "archived"], key="adm-pj-status")
                p_notes = st.text_area("Notes", height=70, key="adm-pj-notes")
            if st.button("💾 Save project", type="primary", key="adm-pj-save"):
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
                        if actions[1].button("✏️ Edit", key=f"adm-pj-edit-{p['name']}", use_container_width=True):
                            ss[f"editing-pj-{p['name']}"] = True
                        if actions[2].button("🗑 Delete", key=f"adm-pj-del-{p['name']}", use_container_width=True):
                            if memory.delete_project_admin(p["name"]):
                                log("admin_delete_project", details={"name": p["name"]})
                                st.toast(f"Deleted project {p['name']}")
                                st.rerun()
                    else:
                        actions[1].caption("(auto-inferred from past quote — promote by editing)")
                        if actions[2].button("📌 Promote to managed", key=f"adm-pj-promote-{p['name']}", use_container_width=True):
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
                            saved = sb1.form_submit_button("💾 Save changes", type="primary", use_container_width=True)
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
        # Backfill + Backup banner
        with st.container(border=True):
            bcols = st.columns([2, 1, 1])
            with bcols[0]:
                st.markdown("**Backfill from past quotes**")
                st.caption("Sweep every line item from `issued_quote_items` into the catalog (catches items missed before the learning hook was wired).")
            with bcols[1]:
                if st.button("🔄 Backfill catalog", use_container_width=True, type="primary"):
                    n = memory.backfill_learned_items_from_quotes()
                    log("backfill_catalog", details={"items_processed": n})
                    st.toast(f"Backfilled {n} item(s) from past quotes", icon="✅")
                    st.rerun()
            with bcols[2]:
                # DB backup — copy memory.sqlite into the work folder with a timestamp
                if st.button("💾 Backup DB", use_container_width=True,
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
                        if st.button("🗑", key=f"cat-del-{norm[:60]}", help="Remove from catalog"):
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
                        if st.button("Save", key=f"cat-save-{norm[:60]}", use_container_width=True):
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
                if st.button(f"💾 Save to work folder ({ss.work_folder}\\reviews\\)",
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
                    if st.button("Save", key=f"saverate-{entry['code']}"):
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
        if st.button("Apply uplift", key="bulk-apply"):
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
    st.subheader("Audit log")
    st.caption("Every quantity/rate change, confirmation, lock, undo, and issue. Persisted for the session.")
    if not ss.audit_log:
        st.info("No audit entries yet.")
    else:
        for e in reversed(ss.audit_log):
            ts = e["ts"]
            action = e["action"]
            iid = e.get("item_id") or ""
            details = e.get("details") or {}
            st.code(f"{ts}  {action:<22} {iid:<10} {json.dumps(details, default=str)}", language=None)
