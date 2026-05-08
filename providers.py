"""LLM provider abstraction.

QSLite started Anthropic-only. This module routes the same calls to either
Anthropic (Claude), xAI (Grok), or Groq (Llama on LPUs) via their respective
endpoints without rewriting extract.py and voice_edits.py.

Three providers:
  - "anthropic" — Claude Sonnet/Haiku via native SDK
  - "grok"      — xAI Grok via OpenAI SDK at api.x.ai/v1 (paid)
  - "groq"      — Groq (Llama / Mixtral on LPUs) via OpenAI SDK at
                  api.groq.com/openai/v1. Has a real free tier with
                  rate limits.

Provider is chosen by `EXTRACTION_PROVIDER` env var (or st.secrets) at call
time. Models are overridable via:
  - ANTHROPIC_VISION_MODEL  (default: claude-sonnet-4-5)
  - ANTHROPIC_TEXT_MODEL    (default: claude-haiku-4-5-20251001)
  - GROK_VISION_MODEL       (default: grok-2-vision-1212)
  - GROK_TEXT_MODEL         (default: grok-3-mini)
  - GROQ_VISION_MODEL       (default: llama-3.2-90b-vision-preview)
  - GROQ_TEXT_MODEL         (default: llama-3.3-70b-versatile)

Public surface:
  - active_provider() -> "anthropic" | "grok" | "groq"
  - has_provider_key(provider=None) -> bool
  - call_with_tools(messages, system, tools, tool_choice, kind, max_tokens) -> ToolCallResult
  - call_text(messages, system, kind, max_tokens) -> str

`messages` uses the Anthropic shape as canonical:
  [{"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}]}]
The Grok/Groq branches translate to OpenAI's chat.completions shape internally.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional


def _read_env_or_secret(*keys: str) -> Optional[str]:
    """Read from os.environ first, fall back to st.secrets if available."""
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v
    try:
        import streamlit as st  # type: ignore
        for k in keys:
            v = st.secrets.get(k)
            if v:
                return v
    except Exception:
        pass
    return None


def active_provider() -> str:
    """Return 'anthropic' | 'grok' | 'groq'. Defaults to 'anthropic'."""
    p = (_read_env_or_secret("EXTRACTION_PROVIDER", "QSLITE_PROVIDER") or "anthropic").strip().lower()
    if p in ("grok", "xai"):
        return "grok"
    if p in ("groq", "llama"):
        return "groq"
    return "anthropic"


def has_provider_key(provider: Optional[str] = None) -> bool:
    p = provider or active_provider()
    if p == "grok":
        return bool(_read_env_or_secret("XAI_API_KEY", "GROK_API_KEY"))
    if p == "groq":
        return bool(_read_env_or_secret("GROQ_API_KEY"))
    return bool(_read_env_or_secret("ANTHROPIC_API_KEY"))


def model_for(kind: str, provider: Optional[str] = None) -> str:
    p = provider or active_provider()
    if p == "grok":
        if kind == "vision":
            return _read_env_or_secret("GROK_VISION_MODEL") or "grok-2-vision-1212"
        return _read_env_or_secret("GROK_TEXT_MODEL") or "grok-3-mini"
    if p == "groq":
        if kind == "vision":
            return _read_env_or_secret("GROQ_VISION_MODEL") or "llama-3.2-90b-vision-preview"
        return _read_env_or_secret("GROQ_TEXT_MODEL") or "llama-3.3-70b-versatile"
    if kind == "vision":
        return _read_env_or_secret("ANTHROPIC_VISION_MODEL") or "claude-sonnet-4-5"
    return _read_env_or_secret("ANTHROPIC_TEXT_MODEL") or "claude-haiku-4-5-20251001"


@dataclass
class ToolCallResult:
    name: str
    input: dict


# ---------------------------------------------------------------------------
# Anthropic branch
# ---------------------------------------------------------------------------
def _anthropic_call_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    tool_choice: Optional[dict],
    kind: str,
    max_tokens: int,
) -> ToolCallResult:
    import anthropic
    client = anthropic.Anthropic(api_key=_read_env_or_secret("ANTHROPIC_API_KEY"))
    kwargs: dict[str, Any] = dict(
        model=model_for(kind, "anthropic"),
        max_tokens=max_tokens,
        system=system,
        tools=tools,
        messages=messages,
    )
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    response = client.messages.create(**kwargs)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        # Fall back to first text block as a stub clarification
        text = next((b.text for b in response.content if b.type == "text"), "")
        return ToolCallResult(name="ask_clarification",
                              input={"question": text or "Model returned no tool call."})
    return ToolCallResult(name=tool_use.name, input=dict(tool_use.input))


def _anthropic_call_text(
    messages: list[dict],
    system: str,
    kind: str,
    max_tokens: int,
) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=_read_env_or_secret("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=model_for(kind, "anthropic"),
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in response.content if b.type == "text")


# ---------------------------------------------------------------------------
# Grok branch (OpenAI-compatible API at api.x.ai/v1)
# ---------------------------------------------------------------------------
def _anthropic_to_openai_content(content: Any) -> Any:
    """Translate an Anthropic-style content block (or list of blocks, or string)
    to OpenAI chat.completions content shape."""
    if isinstance(content, str):
        return content
    out: list[dict] = []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            out.append({"type": "text", "text": block["text"]})
        elif btype == "image":
            src = block.get("source") or {}
            if src.get("type") == "base64":
                media = src.get("media_type", "image/png")
                data = src.get("data", "")
                out.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media};base64,{data}"},
                })
            elif src.get("type") == "url":
                out.append({
                    "type": "image_url",
                    "image_url": {"url": src.get("url", "")},
                })
    return out


def _anthropic_messages_to_openai(messages: list[dict], system: str) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role", "user")
        out.append({"role": role, "content": _anthropic_to_openai_content(m.get("content"))})
    return out


def _anthropic_tool_to_openai(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or {"type": "object"},
        },
    }


def _anthropic_tool_choice_to_openai(tc: Optional[dict]) -> Any:
    if not tc:
        return "auto"
    if tc.get("type") == "tool":
        return {"type": "function", "function": {"name": tc.get("name")}}
    if tc.get("type") == "any":
        return "required"
    if tc.get("type") == "auto":
        return "auto"
    return "auto"


_OPENAI_COMPAT_CONFIG = {
    "grok": {
        "base_url": "https://api.x.ai/v1",
        "key_names": ("XAI_API_KEY", "GROK_API_KEY"),
        "label": "xAI Grok",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_names": ("GROQ_API_KEY",),
        "label": "Groq",
    },
}


def _openai_compat_client(provider: str):
    cfg = _OPENAI_COMPAT_CONFIG.get(provider)
    if not cfg:
        raise RuntimeError(f"Unknown OpenAI-compatible provider: {provider}")
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            f"{cfg['label']} provider requires `openai` package. Add openai>=1.0 to requirements.txt."
        ) from e
    api_key = _read_env_or_secret(*cfg["key_names"])
    if not api_key:
        raise RuntimeError(f"{cfg['key_names'][0]} not set. Add it via the sidebar or .env.")
    return OpenAI(api_key=api_key, base_url=cfg["base_url"])


def _openai_compat_call_with_tools(
    provider: str,
    messages: list[dict],
    system: str,
    tools: list[dict],
    tool_choice: Optional[dict],
    kind: str,
    max_tokens: int,
) -> ToolCallResult:
    client = _openai_compat_client(provider)
    oai_messages = _anthropic_messages_to_openai(messages, system)
    oai_tools = [_anthropic_tool_to_openai(t) for t in tools]
    oai_tc = _anthropic_tool_choice_to_openai(tool_choice)
    kwargs: dict[str, Any] = dict(
        model=model_for(kind, provider),
        max_tokens=max_tokens,
        messages=oai_messages,
        tools=oai_tools,
        tool_choice=oai_tc,
    )
    response = client.chat.completions.create(**kwargs)
    msg = response.choices[0].message
    calls = getattr(msg, "tool_calls", None) or []
    if not calls:
        text = msg.content or ""
        # Some Groq models (vision in particular) may not emit tool_calls.
        # Last-ditch: try to recover JSON args from the raw text.
        if text:
            try:
                # Strip markdown code fences if any
                cleaned = text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.strip("`")
                    if cleaned.lower().startswith("json"):
                        cleaned = cleaned[4:].lstrip()
                start = cleaned.find("{")
                end = cleaned.rfind("}")
                if start != -1 and end != -1 and end > start:
                    parsed = json.loads(cleaned[start:end + 1])
                    target = (tool_choice or {}).get("name") if (tool_choice or {}).get("type") == "tool" else None
                    if target and isinstance(parsed, dict):
                        return ToolCallResult(name=target, input=parsed)
            except Exception:
                pass
        return ToolCallResult(name="ask_clarification",
                              input={"question": text or f"{provider} returned no tool call."})
    call = calls[0]
    name = call.function.name
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    return ToolCallResult(name=name, input=args)


def _openai_compat_call_text(
    provider: str,
    messages: list[dict],
    system: str,
    kind: str,
    max_tokens: int,
) -> str:
    client = _openai_compat_client(provider)
    oai_messages = _anthropic_messages_to_openai(messages, system)
    response = client.chat.completions.create(
        model=model_for(kind, provider),
        max_tokens=max_tokens,
        messages=oai_messages,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------
def call_with_tools(
    messages: list[dict],
    system: str,
    tools: list[dict],
    tool_choice: Optional[dict] = None,
    kind: str = "vision",
    max_tokens: int = 8192,
) -> ToolCallResult:
    p = active_provider()
    if p in ("grok", "groq"):
        return _openai_compat_call_with_tools(p, messages, system, tools, tool_choice, kind, max_tokens)
    return _anthropic_call_with_tools(messages, system, tools, tool_choice, kind, max_tokens)


def call_text(
    messages: list[dict],
    system: str,
    kind: str = "text",
    max_tokens: int = 2048,
) -> str:
    p = active_provider()
    if p in ("grok", "groq"):
        return _openai_compat_call_text(p, messages, system, kind, max_tokens)
    return _anthropic_call_text(messages, system, kind, max_tokens)
