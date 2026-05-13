"""Auto-source SA market rates for extracted items that don't match the catalogue.

When the rate matcher fails (returns no candidate), we ask the active LLM
provider for the most affordable South African market rate that still meets
a reasonable quality floor. The result is annotated so the user always sees
that the rate was auto-sourced (and can override).

Routes through providers.call_with_tools() so it honours EXTRACTION_PROVIDER
(gemini, groq, ollama, grok, anthropic). Falls back gracefully if no provider
is configured.
"""
from __future__ import annotations

from typing import Optional

import providers
from schema import ExtractedItem


SYSTEM_PROMPT = """You are an expert South African quantity surveyor. Given a single \
construction line item that the user could not match against their internal rate \
catalogue, suggest a single all-inclusive supply-and-fit unit rate for the South \
African market in 2026.

Rules:
- Spec on the AFFORDABLE end of the range (cost-conscious but reputable supplier, \
  no premium brands) — the user wants a baseline cost, not a luxury rate.
- Output ZAR (Rand) per the unit specified.
- Be honest with `confidence` (0-1). If you have no good public data for this exact \
  description, drop confidence below 0.5.
- Always include a short `reasoning` line — 1 sentence — that names a public source \
  category or the comparable item you anchored on (e.g. "midpoint of typical SA \
  basic-tier {trade} install rate, public sources Apr-2026").
- Always include a `source_note` with where this rate was anchored (publicly known \
  SA construction-cost ranges, trade-specific online quotes, retail averages).
"""


PRICE_TOOL = {
    "name": "suggest_unit_rate",
    "description": "Return a single suggested unit rate in ZAR for a South African construction line item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rate_zar": {"type": "number", "exclusiveMinimum": 0,
                          "description": "Suggested unit rate in ZAR (Rand)."},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
            "source_note": {"type": "string"},
        },
        "required": ["rate_zar", "confidence", "reasoning", "source_note"],
    },
}


def auto_rate_item(item: ExtractedItem) -> Optional[dict]:
    """Returns dict with keys rate_zar, confidence, reasoning, source_note — or None on failure.

    Uses the active provider (EXTRACTION_PROVIDER env). Free if pointed at Gemini/Groq/Ollama.
    """
    user_text = (
        "Suggest an affordable SA market unit rate for this single line item:\n\n"
        f"- Description: {item.description}\n"
        f"- Trade: {item.trade}\n"
        f"- Unit: {item.unit}\n"
        f"- Quantity to be priced: {item.quantity} {item.unit}\n"
        f"- Notes from extraction: {item.notes or '(none)'}\n\n"
        "Respond via the suggest_unit_rate tool. ZAR per unit, supply-and-fit, "
        "affordable tier, 2026 South African market."
    )
    try:
        result = providers.call_with_tools(
            messages=[{"role": "user", "content": [{"type": "text", "text": user_text}]}],
            system=SYSTEM_PROMPT,
            tools=[PRICE_TOOL],
            tool_choice={"type": "tool", "name": "suggest_unit_rate"},
            kind="text",
            max_tokens=512,
        )
    except Exception:
        return None

    if result is None or not getattr(result, "input", None):
        return None
    raw = result.input
    try:
        rate = float(raw["rate_zar"])
        if rate <= 0:
            return None
        provider_name = providers.active_provider()
        return {
            "rate_zar": round(rate, 2),
            "confidence": float(raw.get("confidence", 0.5)),
            "reasoning": str(raw.get("reasoning", "")),
            "source_note": str(raw.get("source_note", f"auto-sourced via {provider_name} (SA market knowledge, 2026)")),
        }
    except (KeyError, TypeError, ValueError):
        return None
