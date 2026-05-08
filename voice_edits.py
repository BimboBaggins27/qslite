"""Verbal-edits feature.

User speaks instructions like 'drop the carpenter rate by 10% and add a labourer day' →
this module parses that with Claude into a structured list of edit ops, which the app
previews as a diff and applies on confirm.
"""
from __future__ import annotations

import uuid
from typing import Optional

import providers
from schema import LineItem, Provenance, EditState


EDIT_TOOL = {
    "name": "apply_quote_edits",
    "description": (
        "Parse the user's verbal instruction into a list of structured edits. "
        "Each edit targets either a specific line item (by id) or a header field. "
        "Use delta_pct for percentage adjustments (e.g. 'drop the rate by 10%'). "
        "Use absolute values for explicit numbers (e.g. 'set rate to 2000')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {
                            "type": "string",
                            "enum": ["modify_item", "add_item", "remove_item", "modify_header"],
                        },
                        "target_item_id": {
                            "type": "string",
                            "description": "For modify_item / remove_item: the id of the affected line item. Pick the closest match by description/trade if the user is vague.",
                        },
                        "field": {
                            "type": "string",
                            "description": "For modify_item: one of [description, quantity, unit, rate_zar, zone, trade]. For modify_header: one of [client_name, client_address, attention, quote_no, quote_date, re_subject, project, payment_terms].",
                        },
                        "value": {
                            "description": "New absolute value (string or number).",
                        },
                        "delta_pct": {
                            "type": "number",
                            "description": "Percentage change for rate_zar or quantity (e.g. -10 means decrease by 10%). Mutually exclusive with value.",
                        },
                        "new_item": {
                            "type": "object",
                            "description": "For add_item: full spec.",
                            "properties": {
                                "description": {"type": "string"},
                                "trade": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string"},
                                "rate_zar": {"type": "number"},
                                "zone": {"type": "string"},
                            },
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "One short sentence on why you made this edit, in plain English.",
                        },
                    },
                    "required": ["op", "reasoning"],
                },
            },
            "summary": {
                "type": "string",
                "description": "One-line plain-English summary of all edits combined.",
            },
        },
        "required": ["edits"],
    },
}


def _items_summary(items: list[LineItem]) -> str:
    lines = ["Current line items (id · description · qty unit · rate · zone):"]
    for li in items:
        lines.append(
            f"  {li.id} · {li.description[:60]} · {li.quantity} {li.unit} · "
            f"R {li.rate_zar:,.2f} · zone={li.zone}"
        )
    return "\n".join(lines)


def parse_voice_instruction(
    transcript: str,
    items: list[LineItem],
    header: dict,
) -> Optional[dict]:
    """Send the verbal instruction to the active LLM with current quote state. Returns
    {edits: [...], summary: str} or None on failure."""
    if not transcript.strip() or not providers.has_provider_key():
        return None

    system = (
        "You are a quantity surveyor's voice assistant. The user dictates "
        "edits to an in-progress quotation. Translate their instruction into "
        "a list of structured edit operations using the apply_quote_edits "
        "tool. Be precise: prefer delta_pct for percentage talk, absolute "
        "value otherwise. If the user is vague about which item, match by "
        "description/trade keywords. If you can't tell what they want, "
        "return an empty edits array with a summary explaining why."
    )

    items_text = _items_summary(items)
    header_keys = ["client_name", "client_address", "attention", "quote_no",
                    "quote_date", "re_subject", "project", "payment_terms"]
    header_summary = "\n".join([
        f"  {k} = {header.get(k, '')!r}" for k in header_keys if header.get(k)
    ]) or "  (header is empty)"

    user_msg = (
        f"USER VERBAL INSTRUCTION:\n\"{transcript.strip()}\"\n\n"
        f"{items_text}\n\n"
        f"Current quote header:\n{header_summary}\n\n"
        f"Translate the instruction into apply_quote_edits."
    )

    try:
        result = providers.call_with_tools(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            tools=[EDIT_TOOL],
            tool_choice={"type": "tool", "name": "apply_quote_edits"},
            kind="text",
            max_tokens=2048,
        )
    except Exception:
        return None

    if result.name != "apply_quote_edits":
        return None
    return result.input


def apply_edits(
    items: list[LineItem],
    header: dict,
    edits: list[dict],
) -> tuple[list[LineItem], dict, list[str]]:
    """Apply a list of edit ops to items + header. Returns (items, header, applied_log)."""
    applied: list[str] = []
    items = list(items)

    for edit in edits:
        op = edit.get("op")
        try:
            if op == "modify_item":
                tid = edit.get("target_item_id")
                li = next((x for x in items if x.id == tid), None)
                if not li:
                    applied.append(f"⚠ skipped (item id {tid} not found): {edit.get('reasoning', '')}")
                    continue
                field = edit.get("field")
                if not field:
                    continue
                if "delta_pct" in edit and edit["delta_pct"] is not None and field in ("rate_zar", "quantity"):
                    old = getattr(li, field)
                    new_val = round(old * (1 + float(edit["delta_pct"]) / 100.0), 2)
                    setattr(li, field, new_val)
                    applied.append(f"✓ {li.description[:30]}: {field} {old} → {new_val} ({edit['delta_pct']:+.1f}%)")
                elif "value" in edit and edit["value"] is not None:
                    new_val = edit["value"]
                    if field in ("rate_zar", "quantity"):
                        new_val = float(new_val)
                    old = getattr(li, field, None)
                    setattr(li, field, new_val)
                    applied.append(f"✓ {li.description[:30]}: {field} {old} → {new_val}")
                if li.state == EditState.AI_SUGGESTED:
                    li.state = EditState.USER_EDITED

            elif op == "remove_item":
                tid = edit.get("target_item_id")
                target = next((x for x in items if x.id == tid), None)
                if target:
                    items = [x for x in items if x.id != tid]
                    applied.append(f"✓ Removed: {target.description[:50]}")
                else:
                    applied.append(f"⚠ skipped remove (id {tid} not found)")

            elif op == "add_item":
                spec = edit.get("new_item") or {}
                if not spec.get("description"):
                    applied.append("⚠ skipped add_item (no description)")
                    continue
                items.append(LineItem(
                    id=uuid.uuid4().hex[:8],
                    description=spec["description"],
                    trade=spec.get("trade", "other"),
                    quantity=float(spec.get("quantity", 1.0)),
                    unit=spec.get("unit", "no"),
                    zone=spec.get("zone", "Default"),
                    rate_zar=float(spec.get("rate_zar", 0.0)),
                    rate_code=None,
                    confidence=1.0,
                    provenance=Provenance(source_image="voice-edit", evidence="added via verbal instruction"),
                    state=EditState.USER_ADDED,
                ))
                applied.append(f"✓ Added: {spec['description'][:50]} ({spec.get('quantity')} {spec.get('unit')} @ R{spec.get('rate_zar', 0)})")

            elif op == "modify_header":
                field = edit.get("field")
                value = edit.get("value")
                if field and value is not None:
                    old = header.get(field, "")
                    header[field] = value
                    applied.append(f"✓ Header.{field}: {old!r} → {value!r}")
        except Exception as e:
            applied.append(f"⚠ skipped (exception): {e}")

    return items, header, applied
