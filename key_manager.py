"""Set/get the Anthropic API key without making the user touch a file.

Saves to .env so the key persists across server restarts, and to the current
process environment so it's picked up on the very next request.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"


def get_api_key() -> str:
    # 1. Process env (set by .env or by save_api_key)
    val = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if val:
        return val
    # 2. Streamlit Cloud secrets (when deployed to share.streamlit.io)
    try:
        import streamlit as st
        secret = st.secrets.get("ANTHROPIC_API_KEY", "")
        if secret:
            os.environ["ANTHROPIC_API_KEY"] = str(secret).strip()
            return os.environ["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return ""


def has_api_key() -> bool:
    return bool(get_api_key())


def save_api_key(key: str) -> None:
    """Write `key` to .env (replace if already present, append otherwise) and
    set it on the running process so the next API call sees it."""
    key = (key or "").strip()
    os.environ["ANTHROPIC_API_KEY"] = key

    line = f"ANTHROPIC_API_KEY={key}"
    if ENV_PATH.exists():
        existing = ENV_PATH.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        replaced = False
        for entry in existing:
            stripped = entry.strip()
            if stripped.startswith("ANTHROPIC_API_KEY="):
                out.append(line)
                replaced = True
            else:
                out.append(entry)
        if not replaced:
            out.append(line)
        ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    else:
        ENV_PATH.write_text(line + "\n", encoding="utf-8")


def clear_api_key() -> None:
    os.environ.pop("ANTHROPIC_API_KEY", None)
    save_api_key("")
