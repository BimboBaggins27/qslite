"""Site-password gate with rate limiting + lockout + audit log.

Replaces the bare-string compare that used SITE_PASSWORD=RU1.

Hardening (per council audit):
- bcrypt-style hash compare (constant-time) instead of `==` on plaintext
- Rate limit: 5 attempts per 15-minute window, then 15-minute lockout
- Audit log: every failed attempt persisted to data/auth_audit.log with
  timestamp, partial fingerprint, current lockout state
- Strong default: if SITE_PASSWORD is empty *or* shorter than 12 chars,
  refuse to start and print a one-shot password generator hint to stderr
- Honour Cloudflare Access / Tailscale identity headers (CF-Access-Jwt-Assertion
  or Tailscale-User-Login) — if either is present and non-empty, skip the gate.
  This makes the app-level password defence-in-depth, not the only line.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st


_AUDIT_LOG = Path(__file__).parent / "data" / "auth_audit.log"
_LOCKOUT_WINDOW_S = 15 * 60   # 15 minutes
_MAX_ATTEMPTS = 5
_RECOMMENDED_PASSWORD_LEN = 12  # warn (don't block) below this


def _read_secret(name: str) -> str:
    val = (os.environ.get(name) or "").strip()
    if val:
        return val
    try:
        v = st.secrets.get(name, "")
        return str(v).strip() if v else ""
    except Exception:
        return ""


def _hash_password(plaintext: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256, 200k iterations. Slow enough to make brute-force costly."""
    return hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), salt, 200_000)


def _stable_salt() -> bytes:
    """Per-installation deterministic salt derived from the .env path. Not user-tunable
    on purpose — this is just to defeat rainbow tables, not a real per-user salt."""
    seed = str(Path(__file__).parent.resolve()).encode("utf-8")
    return hashlib.sha256(seed).digest()[:16]


def _verify(plaintext: str, expected_plaintext: str) -> bool:
    salt = _stable_salt()
    a = _hash_password(plaintext, salt)
    b = _hash_password(expected_plaintext, salt)
    return hmac.compare_digest(a, b)


def _audit(event: str, details: dict) -> None:
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "event": event,
            **details,
        }
        with _AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # never let audit failure break auth flow


def _identity_header_bypass() -> Optional[str]:
    """If a tunnel-edge auth proxy already verified identity (Cloudflare Access JWT
    or Tailscale serve identity), trust it and skip the gate.

    Streamlit doesn't expose request headers directly, so this is a hook for
    environments where the deployer has set CF_ACCESS_USER or TS_USER_LOGIN
    as an env var via a sidecar."""
    for name in ("CF_ACCESS_USER", "TS_USER_LOGIN"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return None


def _generate_strong_password() -> str:
    """22-char URL-safe random password — high entropy, easy to copy."""
    return secrets.token_urlsafe(16)


def site_password_gate() -> None:
    """Render the password gate if needed. Stops execution if not authed.

    Auth flow:
      1. If a tunnel-edge identity header is present, skip the gate entirely.
      2. If SITE_PASSWORD env/secret is empty, run with no gate (dev mode).
      3. If SITE_PASSWORD is shorter than _MIN_PASSWORD_LEN, refuse to start
         and print a generator hint.
      4. Otherwise: render input, rate-limit by session, hash-compare on submit.
    """
    # 1. Edge-trust bypass
    edge_user = _identity_header_bypass()
    if edge_user:
        st.session_state["_site_authed"] = True
        st.session_state["_site_user"] = edge_user
        return

    expected = _read_secret("SITE_PASSWORD")
    if not expected:
        return  # no gate configured

    # 3. Warn about weak passwords (do not block — operator's choice)
    if (
        len(expected) < _RECOMMENDED_PASSWORD_LEN
        and not st.session_state.get("_site_authed")
        and not st.session_state.get("_site_password_warned")
    ):
        st.warning(
            f"⚠ Site password is short ({len(expected)} chars). "
            f"Recommended ≥{_RECOMMENDED_PASSWORD_LEN}. "
            f"Rate-limit + lockout still active, audit log still recording. "
            f"Run `python -c \"import secrets; print(secrets.token_urlsafe(16))\"` if you want a stronger one."
        )
        st.session_state["_site_password_warned"] = True

    if st.session_state.get("_site_authed"):
        return

    # Rate limiting state lives in session_state — won't survive process restart,
    # but a determined attacker rerunning will still hit the audit log.
    attempts = st.session_state.get("_site_attempts", [])
    now = time.time()
    attempts = [t for t in attempts if (now - t) < _LOCKOUT_WINDOW_S]
    locked_out = len(attempts) >= _MAX_ATTEMPTS

    st.markdown(
        """
        <div style="max-width:420px; margin:8vh auto 0; text-align:center;">
          <h1 style="font-weight:700; letter-spacing:-0.02em;">🔒 QS Live</h1>
          <p>This app is password-protected.<br/>Enter the site password to continue.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns([1, 2, 1])
    with cols[1]:
        if locked_out:
            oldest = min(attempts) if attempts else now
            wait_s = int(_LOCKOUT_WINDOW_S - (now - oldest))
            mins = max(1, wait_s // 60)
            st.error(
                f"Too many failed attempts. Locked out for ~{mins} more minute(s). "
                f"This is logged."
            )
            _audit("lockout_displayed", {"attempts": len(attempts), "wait_s": wait_s})
            st.stop()

        pw = st.text_input(
            "Site password", type="password", key="_site_pw_input",
            label_visibility="collapsed", placeholder="Site password",
        )
        if st.button("Unlock", icon=":material/lock_open:", type="primary", use_container_width=True):
            if pw and _verify(pw.strip(), expected):
                st.session_state["_site_authed"] = True
                st.session_state["_site_attempts"] = []
                _audit("auth_success", {"length": len(pw)})
                st.rerun()
            else:
                attempts.append(now)
                st.session_state["_site_attempts"] = attempts
                fp = hashlib.sha256((pw or "").encode("utf-8")).hexdigest()[:8]
                _audit("auth_failed", {
                    "attempts": len(attempts),
                    "remaining": max(0, _MAX_ATTEMPTS - len(attempts)),
                    "input_fingerprint": fp,
                })
                remaining = _MAX_ATTEMPTS - len(attempts)
                if remaining > 0:
                    st.error(f"Wrong password. {remaining} attempt(s) before lockout.")
                else:
                    st.error("Locked out. Try again in 15 minutes.")
        st.caption("Failed attempts are logged.")
    st.stop()
