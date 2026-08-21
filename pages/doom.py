# -*- coding: utf-8 -*-
"""Doom List — live Ndlovu action list on the phone.

Data: encrypted blob in a public side repo (ru1-data/doom.enc). This page
fetches it fresh, derives the Fernet key from SITE_PASSWORD server-side and
decrypts in memory. Nothing readable ever sits in a repo.

The agent republishes on every list change (doom_publish.py); a pull-down /
Refresh here shows it seconds later. No redeploy, no reinstall.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time

import requests
import streamlit as st

st.set_page_config(page_title="NDL Doom List", page_icon="🐘", layout="centered")

from auth import site_password_gate  # noqa: E402  (must run after set_page_config)

site_password_gate()

RAW = "https://raw.githubusercontent.com/BimboBaggins27/ru1-data/main/doom.enc"
SALT, ITERS = b"ndl-doom-v1", 600_000
GLYPH = {"DONE": "✓", "OPEN": "●", "WAITING": "○", "PARKED": "—"}
PORDER = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "—": 4}
PCOLOR = {"URGENT": "#B3261E", "HIGH": "#8a6d1d", "MEDIUM": "#595959", "LOW": "#8a8a8a",
          "—": "#8a8a8a"}


def _password() -> str:
    v = (os.environ.get("SITE_PASSWORD") or "").strip()
    if v:
        return v
    try:
        return str(st.secrets.get("SITE_PASSWORD", "")).strip()
    except Exception:
        return ""


def _decrypt(blob: bytes, pw: str) -> dict:
    from cryptography.fernet import Fernet
    raw = hashlib.pbkdf2_hmac("sha256", pw.encode("utf8"), SALT, ITERS)
    return json.loads(Fernet(base64.urlsafe_b64encode(raw)).decrypt(blob).decode("utf8"))


@st.cache_data(ttl=20, show_spinner=False)
def _fetch(ts_bucket: int) -> bytes:
    r = requests.get(f"{RAW}?ts={ts_bucket}", timeout=15,
                     headers={"Cache-Control": "no-cache"})
    r.raise_for_status()
    return r.content


def load() -> dict:
    pw = _password()
    if not pw:
        st.error("SITE_PASSWORD not configured — cannot derive the data key.")
        st.stop()
    try:
        return _decrypt(_fetch(int(time.time() // 20)), pw)
    except Exception:
        st.error("Data key mismatch or feed unreachable — tell the agent "
                 "(cloud SITE_PASSWORD must match the publisher's).")
        st.stop()


d = load()
rows = d["rows"]

st.markdown(
    "<style>"
    ".block-container{padding-top:1.2rem;max-width:46rem}"
    ".doom-key{background:#F2F0EA;border-left:4px solid #C3A16B;padding:.5rem .8rem;"
    "border-radius:4px;font-size:.9rem;margin-bottom:.6rem}"
    ".doom-row{border-bottom:1px solid #e8e5de;padding:.35rem 0;font-size:.92rem}"
    ".doom-why{color:#6b6b6b;font-size:.8rem;margin:.1rem 0 .3rem 1.4rem}"
    "</style>",
    unsafe_allow_html=True)

st.markdown("### 🐘 NDLOVU — DOOM LIST")
c = {"DONE": 0, "OPEN": 0, "WAITING": 0, "PARKED": 0, "URG": 0}
for r in rows:
    c[r["status"]] += 1
    if r["pri"] == "URGENT" and r["status"] in ("OPEN", "WAITING"):
        c["URG"] += 1
st.markdown(
    f"<div class='doom-key'><b>revised {d.get('revised', '')}</b> · "
    f"done <b>{c['DONE']}</b> · open <b>{c['OPEN']}</b> · waiting <b>{c['WAITING']}</b> · "
    f"parked {c['PARKED']} · <span style='color:#B3261E'>URGENT <b>{c['URG']}</b></span></div>",
    unsafe_allow_html=True)

top = st.columns([1.2, 1.2, 2.6])
urgent_only = top[0].toggle("URGENT", value=False)
hide_done = top[1].toggle("hide ✓", value=True)
needle = top[2].text_input("search", "", placeholder="search job / action / why",
                           label_visibility="collapsed").strip().lower()
if st.button("↻ Refresh now", use_container_width=True):
    _fetch.clear()
    st.rerun()

dated = [r for r in rows if r["status"] in ("OPEN", "WAITING")
         and r.get("due") and r["due"] not in ("you", "them", "Ruben")]
if dated and not needle:
    with st.expander(f"⏱ Dated queue ({len(dated)})", expanded=True):
        for r in sorted(dated, key=lambda x: PORDER[x["pri"]]):
            st.markdown(
                f"<div class='doom-row'><b>{r['due']}</b> — {r['job']}: "
                f"{r['action']}</div>", unsafe_allow_html=True)

def keep(r):
    if urgent_only and not (r["pri"] == "URGENT" and r["status"] in ("OPEN", "WAITING")):
        return False
    if hide_done and r["status"] == "DONE":
        return False
    if needle and needle not in (r["job"] + r["action"] + r["why"]).lower():
        return False
    return True

jobs: dict[str, list] = {}
for r in rows:
    if keep(r):
        jobs.setdefault(r["job"], []).append(r)

def jkey(item):
    rs = item[1]
    urg = sum(1 for r in rs if r["pri"] == "URGENT" and r["status"] in ("OPEN", "WAITING"))
    live = sum(1 for r in rs if r["status"] in ("OPEN", "WAITING"))
    return (-urg, -live, item[0])

shown = 0
for job, rs in sorted(jobs.items(), key=jkey):
    live = [r for r in rs if r["status"] in ("OPEN", "WAITING")]
    urg = sum(1 for r in live if r["pri"] == "URGENT")
    label = f"{job} — {len(live)} live" + (f" · {urg} URGENT" if urg else "")
    with st.expander(label, expanded=bool(urg) and not needle):
        order = {"OPEN": 0, "WAITING": 0, "PARKED": 1, "DONE": 2}
        for r in sorted(rs, key=lambda x: (order[x["status"]], PORDER[x["pri"]])):
            col = PCOLOR[r["pri"]]
            pri = "" if r["status"] == "DONE" else (
                f" <span style='color:{col};font-size:.75rem'><b>{r['pri']}</b></span>")
            due = f" · <b>{r['due']}</b>" if r.get("due") else ""
            st.markdown(
                f"<div class='doom-row'>{GLYPH[r['status']]}{pri} {r['action']}{due}</div>"
                + (f"<div class='doom-why'>{r['why']}</div>" if r["why"] else ""),
                unsafe_allow_html=True)
            shown += 1

st.caption(f"{shown} items shown · ✓ done  ● open  ○ waiting  — parked · "
           "data updates the moment the agent republishes — just pull refresh")
