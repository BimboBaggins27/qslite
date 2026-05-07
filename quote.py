from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from schema import (
    AuditEntry,
    EditState,
    ExtractedItem,
    ExtractionResult,
    LineItem,
    Provenance,
    Rate,
)
from rates import match_rate
from validators import high_value_blockers

try:
    from auto_rate import auto_rate_item
except Exception:
    auto_rate_item = None  # graceful fallback if module missing


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def line_items_from_extraction(result: ExtractionResult) -> list[LineItem]:
    """Build LineItems from an ExtractionResult.

    Rate priority:
    1. The AI's own choice (it.rate_zar) — preferred, since the AI saw the catalogue
       and either picked a code or proposed a context-specific rate.
    2. Catalogue lookup by rate_code if AI provided one but not a numeric rate.
    3. Fuzzy match against the catalogue as a last resort.
    """
    from rates import load_rates  # local to avoid circular import on cold load
    catalogue = {r.code: r for r in load_rates()}

    items: list[LineItem] = []
    for it in result.items:
        # 1) AI provided rate_code → look it up for valid_from / age
        cat_rate = catalogue.get(it.rate_code) if it.rate_code else None

        # 2) AI provided numeric rate but no code → use as-is
        if it.rate_zar is not None and it.rate_zar > 0:
            chosen_rate = it.rate_zar
            chosen_code = it.rate_code if cat_rate else None
            age_days = cat_rate.age_days() if cat_rate else None
        elif cat_rate:  # only code, no number
            chosen_rate = cat_rate.rate_zar
            chosen_code = cat_rate.code
            age_days = cat_rate.age_days()
        else:
            # 3) Fuzzy fallback — only when AI gave us nothing usable
            fallback = match_rate(it)
            chosen_rate = fallback.rate_zar if fallback else 0.0
            chosen_code = fallback.code if fallback else None
            age_days = fallback.age_days() if fallback else None

        items.append(LineItem(
            id=_new_id(),
            description=it.description,
            trade=it.trade,
            quantity=it.quantity,
            unit=it.unit,
            zone=it.zone or "Default",
            rate_zar=chosen_rate,
            rate_code=chosen_code,
            rate_age_days=age_days,
            confidence=it.confidence,
            provenance=it.provenance,
            notes=it.notes,
            state=EditState.AI_SUGGESTED,
        ))
    return items


def _line_from_extracted(it: ExtractedItem, rate: Optional[Rate]) -> LineItem:
    """Legacy helper — kept for compatibility but no longer the primary path."""
    return LineItem(
        id=_new_id(),
        description=it.description,
        trade=it.trade,
        quantity=it.quantity,
        unit=it.unit,
        zone=it.zone or "Default",
        rate_zar=(it.rate_zar if it.rate_zar else (rate.rate_zar if rate else 0.0)),
        rate_code=it.rate_code or (rate.code if rate else None),
        rate_age_days=rate.age_days() if rate else None,
        confidence=it.confidence,
        provenance=it.provenance,
        notes=it.notes,
        state=EditState.AI_SUGGESTED,
    )


def quote_total(items: list[LineItem]) -> float:
    return round(sum(i.total_zar for i in items), 2)


def trade_subtotals(items: list[LineItem]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i in items:
        out[i.trade] = round(out.get(i.trade, 0.0) + i.total_zar, 2)
    return out


def can_issue(items: list[LineItem]) -> tuple[bool, list[str]]:
    """Soft-lock guard. A quote can only be issued when every line item has been
    reviewed by a human and no red-confidence items remain unconfirmed."""
    blockers: list[str] = []
    if not items:
        return False, ["Quote has no line items."]

    for i in items:
        if i.state == EditState.AI_SUGGESTED:
            blockers.append(f"Item {i.id} ({i.description}) still in AI-suggested state — review required.")
        if i.confidence < 0.5 and i.state != EditState.USER_CONFIRMED and i.state != EditState.USER_EDITED:
            blockers.append(f"Item {i.id} has low confidence ({i.confidence:.2f}) and is not user-confirmed.")
        if i.rate_zar <= 0:
            blockers.append(f"Item {i.id} has no rate — set a rate or remove the item.")
    # Two-source rule for high-value items
    blockers.extend(high_value_blockers(items))
    return (len(blockers) == 0), blockers


def blocker_summary(items: list[LineItem]) -> dict:
    """Return blocker counts grouped by category — far more useful than a flat list when there are many items."""
    if not items:
        return {"empty": True, "categories": [], "total": 0}

    pending_review = [i for i in items if i.state == EditState.AI_SUGGESTED]
    no_rate = [i for i in items if i.rate_zar <= 0]
    low_conf_unconfirmed = [
        i for i in items
        if i.confidence < 0.5 and i.state not in (EditState.USER_CONFIRMED, EditState.USER_EDITED)
    ]
    hv_unconfirmed = [
        i for i in items
        if i.high_value_review and i.state not in (EditState.USER_CONFIRMED, EditState.USER_ADDED)
    ]

    categories = []
    if pending_review:
        categories.append({
            "kind": "pending_review",
            "count": len(pending_review),
            "label": f"{len(pending_review)} item(s) still in AI-suggested state — click ✓ Confirm or use *Confirm all*",
            "ids": [i.id for i in pending_review],
        })
    if no_rate:
        categories.append({
            "kind": "no_rate",
            "count": len(no_rate),
            "label": f"{len(no_rate)} item(s) have no rate — set a rate or remove",
            "ids": [i.id for i in no_rate],
        })
    if low_conf_unconfirmed:
        categories.append({
            "kind": "low_confidence",
            "count": len(low_conf_unconfirmed),
            "label": f"{len(low_conf_unconfirmed)} low-confidence item(s) need explicit confirmation",
            "ids": [i.id for i in low_conf_unconfirmed],
        })
    if hv_unconfirmed:
        categories.append({
            "kind": "high_value",
            "count": len(hv_unconfirmed),
            "label": f"{len(hv_unconfirmed)} high-value item(s) (≥ R 50,000) need explicit confirmation (two-source rule)",
            "ids": [i.id for i in hv_unconfirmed],
        })

    return {"empty": False, "categories": categories, "total": sum(c["count"] for c in categories)}


def freeze_quote(items: list[LineItem], header: Optional[dict] = None) -> dict:
    """Snapshot the quote at issue time — rates, quantities, totals, all immutable from here on."""
    return {
        "issued_at": datetime.utcnow().isoformat(timespec="seconds"),
        "total_zar": quote_total(items),
        "trade_subtotals": trade_subtotals(items),
        "items": [i.model_dump() for i in items],
        "header": header or {},
    }


def audit(actor: str, action: str, item_id: Optional[str] = None, **details) -> AuditEntry:
    return AuditEntry(
        ts=datetime.utcnow().isoformat(timespec="seconds"),
        actor=actor,
        action=action,
        item_id=item_id,
        details=details,
    )
