"""Set/get LLM API keys (Anthropic + xAI Grok) without making the user touch a file.

Saves to .env so keys persist across server restarts, and to the current
process environment so they're picked up on the very next request.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

# Each tuple: (canonical env name, list of accepted aliases for reading from secrets)
KNOWN_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY", []),
    "grok":      ("XAI_API_KEY", ["GROK_API_KEY"]),
}


def _read_secret(name: str, aliases: list[str]) -> str:
    """Read a key from process env, then Streamlit secrets. Caches into env on hit."""
    val = (os.environ.get(name) or "").strip()
    if val:
        return val
    try:
        import streamlit as st
        for k in [name, *aliases]:
            secret = st.secrets.get(k, "")
            if secret:
                v = str(secret).strip()
                os.environ[name] = v
                return v
    except Exception:
        pass
    return ""


def get_api_key(provider: str = "anthropic") -> str:
    name, aliases = KNOWN_KEYS.get(provider, ("ANTHROPIC_API_KEY", []))
    return _read_secret(name, aliases)


def has_api_key(provider: str = "anthropic") -> bool:
    return bool(get_api_key(provider))


def save_api_key(key: str, provider: str = "anthropic") -> None:
    """Write `key` to .env (replace if already present, append otherwise) and
    set it on the running process so the next API call sees it."""
    name, _ = KNOWN_KEYS.get(provider, ("ANTHROPIC_API_KEY", []))
    key = (key or "").strip()
    os.environ[name] = key

    line = f"{name}={key}"
    if ENV_PATH.exists():
        existing = ENV_PATH.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        replaced = False
        for entry in existing:
            stripped = entry.strip()
            if stripped.startswith(f"{name}="):
                out.append(line)
                replaced = True
            else:
                out.append(entry)
        if not replaced:
            out.append(line)
        ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    else:
        ENV_PATH.write_text(line + "\n", encoding="utf-8")


def clear_api_key(provider: str = "anthropic") -> None:
    name, _ = KNOWN_KEYS.get(provider, ("ANTHROPIC_API_KEY", []))
    os.environ.pop(name, None)
    save_api_key("", provider)


def save_provider_choice(provider: str) -> None:
    """Persist EXTRACTION_PROVIDER selection in .env + process env."""
    provider = (provider or "anthropic").strip().lower()
    if provider not in ("anthropic", "grok"):
        provider = "anthropic"
    os.environ["EXTRACTION_PROVIDER"] = provider
    line = f"EXTRACTION_PROVIDER={provider}"
    if ENV_PATH.exists():
        existing = ENV_PATH.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        replaced = False
        for entry in existing:
            if entry.strip().startswith("EXTRACTION_PROVIDER="):
                out.append(line)
                replaced = True
            else:
                out.append(entry)
        if not replaced:
            out.append(line)
        ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    else:
        ENV_PATH.write_text(line + "\n", encoding="utf-8")
