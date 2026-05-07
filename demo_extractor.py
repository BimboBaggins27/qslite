"""Demo (no-API-key) extractor.

Produces a plausible, deterministic ExtractionResult based on the filename and
optional context. Used when no Anthropic API key is set so the rest of the app
(review, learner, locks, Excel export) is fully exercisable for testing.

Every item is tagged with low confidence and provenance flagged "DEMO" so it
can never be confused with a real extraction in the audit trail.
"""
from __future__ import annotations

import hashlib
import random
from typing import Optional

from rates import load_rates
from schema import ExtractedItem, ExtractionResult, Provenance


# Keyword → preferred rate-code prefixes. The first match wins; we still mix in
# random complementary items so each demo extraction looks varied.
KEYWORDS: list[tuple[str, list[str], str]] = [
    # (substring_match, preferred_rate_codes, inferred_zone)
    ("dry", ["DRY-001", "DRY-002", "DRY-003", "DRY-004", "DOR-001", "PNT-001", "PNT-004", "PG-002", "PG-003"], "Building 1"),
    ("wall", ["DRY-001", "MAS-001", "PNT-001", "PNT-005", "DOR-001"], "Wall section"),
    ("bath", ["TIL-001", "TIL-002", "PLM-001", "PLM-002", "PLM-003", "PLM-004", "GLZ-002", "ELC-002", "ELC-003"], "Bathroom"),
    ("kitchen", ["TIL-002", "PLM-005", "CAR-003", "ELC-001", "ELC-003", "PNT-001"], "Kitchen"),
    ("bedroom", ["FIN-002", "PNT-001", "ELC-001", "ELC-002", "DOR-002", "CAR-001"], "Bedroom"),
    ("living", ["FIN-002", "PNT-001", "ELC-003", "ELC-004", "CAR-001"], "Living area"),
    ("exterior", ["PNT-003", "MAS-001"], "Exterior"),
    ("roof", ["PNT-003", "GLZ-001"], "Roof"),
    ("plan", ["DRY-001", "DOR-001", "PNT-001", "TIL-002", "ELC-001"], "Plan area"),
]
DEFAULT_CODES = ["DRY-001", "DRY-002", "DOR-001", "PNT-001", "PNT-004", "TIL-001", "ELC-001", "PG-002"]


def _seed_for(filename: str, extra_context: Optional[str]) -> int:
    h = hashlib.md5(((filename or "") + "::" + (extra_context or "")).encode()).hexdigest()
    return int(h[:8], 16)


def _pick_codes(filename: str, extra_context: Optional[str]) -> tuple[list[str], str]:
    haystack = f"{filename or ''} {extra_context or ''}".lower()
    for substr, codes, zone in KEYWORDS:
        if substr in haystack:
            return codes, zone
    return DEFAULT_CODES, "Default"


def _qty_for(rate, rng: random.Random) -> float:
    """Pick a plausible quantity per unit type."""
    unit = rate.unit
    if unit == "m":
        return round(rng.uniform(3.0, 25.0), 1)
    if unit == "m2":
        return round(rng.uniform(8.0, 80.0), 1)
    if unit == "lin.m":
        return round(rng.uniform(2.0, 30.0), 1)
    if unit == "each":
        return rng.randint(1, 4)
    if unit == "no":
        return rng.randint(1, 5)
    if unit == "kg":
        return round(rng.uniform(5.0, 50.0), 1)
    if unit == "hr":
        return round(rng.uniform(2.0, 16.0), 1)
    return 1.0


def synthesise_extraction(
    image_filename: str,
    extra_context: Optional[str] = None,
    n_items: int = 6,
) -> ExtractionResult:
    """Produce a deterministic demo ExtractionResult."""
    rng = random.Random(_seed_for(image_filename, extra_context))
    rates = load_rates()
    rate_index = {r.code: r for r in rates}

    preferred, zone = _pick_codes(image_filename, extra_context)
    selected_codes: list[str] = []
    for c in preferred:
        if c in rate_index:
            selected_codes.append(c)
        if len(selected_codes) >= n_items:
            break

    items: list[ExtractedItem] = []
    for code in selected_codes:
        rate = rate_index[code]
        items.append(ExtractedItem(
            description=f"[DEMO] {rate.description}",
            trade=rate.trade,
            quantity=_qty_for(rate, rng),
            unit=rate.unit,
            zone=zone,
            confidence=round(rng.uniform(0.30, 0.55), 2),
            provenance=Provenance(
                source_image=image_filename,
                evidence="DEMO MODE — synthetic data, no LLM was called. Verify or replace before issuing.",
                bbox=None,
            ),
            notes="Demo mode — synthetic placeholder. Add your Anthropic API key in the sidebar to enable real vision extraction.",
        ))
    return ExtractionResult(
        items=items,
        overall_notes=f"DEMO MODE — synthesised {len(items)} item(s) for '{image_filename}' (zone: {zone}). No LLM was called.",
    )


def synthesise_pdf_extraction(
    pdf_filename: str,
    n_pages: int,
    extra_context: Optional[str] = None,
) -> ExtractionResult:
    """Produce a demo result for a PDF — one synthetic batch per page."""
    all_items: list[ExtractedItem] = []
    notes: list[str] = []
    for page in range(1, max(1, n_pages) + 1):
        sub = synthesise_extraction(
            f"{pdf_filename}#page-{page}",
            extra_context=extra_context,
            n_items=5,
        )
        all_items.extend(sub.items)
        if sub.overall_notes:
            notes.append(sub.overall_notes)
    return ExtractionResult(items=all_items, overall_notes="\n".join(notes) or None)
