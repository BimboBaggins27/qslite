"""Sanity & anomaly checks.

Two layers:
- per-item sanity ranges (catch obvious extraction nonsense)
- quote-level anomalies (paint area > 3x floor area, draft far above similar past jobs)

Plus the high-value rule: any item whose total exceeds R 50k is flagged for two-source
confirmation (must reach `user_confirmed` and not low-confidence).
"""
from __future__ import annotations

from typing import Optional

from schema import EditState, LineItem


HIGH_VALUE_THRESHOLD_ZAR = 50_000.0


# Per-trade sanity ranges, keyed by (trade, unit). Numbers are conservative
# residential/light-commercial South African defaults — wide enough that legitimate
# extractions pass, narrow enough that hallucinations get caught.
SANITY_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("drywall", "m"): (0.5, 200.0),
    ("drywall", "no"): (1, 50),
    ("tiling", "m2"): (0.5, 200.0),
    ("painting", "m2"): (1.0, 500.0),
    ("plumbing", "each"): (1, 20),
    ("electrical", "each"): (1, 80),
    ("masonry", "m2"): (1.0, 300.0),
    ("glazing", "m2"): (0.3, 50.0),
    ("finishes", "m2"): (1.0, 400.0),
    ("carpentry", "lin.m"): (0.3, 60.0),
    ("carpentry", "each"): (1, 40),
    ("carpentry", "m"): (0.3, 60.0),
    ("carpentry", "no"): (1, 30),
    ("demolition", "m2"): (1.0, 500.0),
    ("demolition", "each"): (1, 60),
    ("pgs", "no"): (1, 100),
}


def sanity_check_item(item: LineItem) -> list[str]:
    """Return list of human-readable warnings, empty if clean."""
    warnings: list[str] = []
    rng = SANITY_RANGES.get((item.trade.lower(), item.unit))
    if rng:
        lo, hi = rng
        if item.quantity < lo:
            warnings.append(f"⚠ Quantity {item.quantity:.2f} {item.unit} is below the typical range for {item.trade} ({lo}-{hi}).")
        if item.quantity > hi:
            warnings.append(f"⚠ Quantity {item.quantity:.2f} {item.unit} is above the typical range for {item.trade} ({lo}-{hi}). Confirm scale or split into multiple items.")
    if item.total_zar >= HIGH_VALUE_THRESHOLD_ZAR:
        warnings.append(
            f"⚠ High-value item (R {item.total_zar:,.2f} ≥ R {HIGH_VALUE_THRESHOLD_ZAR:,.0f}) — two-source rule: must be `user_confirmed` and not low-confidence before issue."
        )
    return warnings


def annotate_items(items: list[LineItem]) -> None:
    """Mutate items in place: populate `sanity_warnings` and `high_value_review`."""
    for it in items:
        it.sanity_warnings = sanity_check_item(it)
        it.high_value_review = it.total_zar >= HIGH_VALUE_THRESHOLD_ZAR


def quote_level_anomalies(items: list[LineItem], similar_avg_total: Optional[float] = None) -> list[str]:
    """Return list of quote-level warning messages."""
    warnings: list[str] = []
    if not items:
        return warnings

    # Floor-area cross-check: sum of floor-related m2 (tiling, finishes, demolition with m2 unit)
    # vs paint m2. If paint > 3x floor, suspicious.
    floor_m2 = sum(
        i.quantity for i in items
        if i.unit == "m2" and i.trade.lower() in ("tiling", "finishes", "demolition")
    )
    paint_m2 = sum(
        i.quantity for i in items
        if i.unit == "m2" and i.trade.lower() == "painting"
    )
    if floor_m2 > 0 and paint_m2 > 3 * floor_m2:
        warnings.append(
            f"⚠ Paint area ({paint_m2:.1f} m²) exceeds 3× floor-related area ({floor_m2:.1f} m²). "
            "Likely double-counted walls or wrong unit."
        )

    # Draft total far above similar past jobs
    if similar_avg_total is not None and similar_avg_total > 0:
        total = sum(i.total_zar for i in items)
        if total > 1.6 * similar_avg_total:
            warnings.append(
                f"⚠ Draft total R {total:,.0f} is {total/similar_avg_total:.1f}× the average of similar past quotes (R {similar_avg_total:,.0f}). Review before issue."
            )
        elif total < 0.5 * similar_avg_total and total > 0:
            warnings.append(
                f"⚠ Draft total R {total:,.0f} is only {total/similar_avg_total:.1f}× the average of similar past quotes (R {similar_avg_total:,.0f}). May be missing items."
            )

    # High-value items not yet confirmed
    pending_high_value = [
        i for i in items
        if i.high_value_review and i.state not in (EditState.USER_CONFIRMED,)
    ]
    if pending_high_value:
        warnings.append(
            f"⚠ {len(pending_high_value)} high-value item(s) (≥ R {HIGH_VALUE_THRESHOLD_ZAR:,.0f}) still need explicit confirmation."
        )

    return warnings


def high_value_blockers(items: list[LineItem]) -> list[str]:
    """Items that should block issue under the two-source rule."""
    blockers: list[str] = []
    for i in items:
        if not i.high_value_review:
            continue
        if i.state != EditState.USER_CONFIRMED and i.state != EditState.USER_ADDED:
            blockers.append(f"High-value item {i.id} ({i.description}) — must be user_confirmed before issue (two-source rule).")
        if i.confidence < 0.5 and i.state == EditState.AI_SUGGESTED:
            blockers.append(f"High-value item {i.id} has low confidence — needs explicit confirmation.")
    return blockers
