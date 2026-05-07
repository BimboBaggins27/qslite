from __future__ import annotations

import json
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Optional

from schema import ExtractedItem, Rate

RATES_PATH = Path(__file__).parent / "data" / "rates.json"


@lru_cache(maxsize=1)
def load_rates() -> list[Rate]:
    raw = json.loads(RATES_PATH.read_text(encoding="utf-8"))
    return [Rate(**r) for r in raw]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_rate(item: ExtractedItem) -> Optional[Rate]:
    """Pick the best rate for an extracted item.

    Strategy: filter rates by trade and matching unit, then pick the highest
    description-similarity match. Returns None if nothing in the catalogue fits.
    """
    candidates = [
        r for r in load_rates()
        if r.trade.lower() == item.trade.lower() and r.unit == item.unit
    ]
    if not candidates:
        candidates = [r for r in load_rates() if r.unit == item.unit]
    if not candidates:
        return None

    scored = sorted(
        candidates,
        key=lambda r: _similarity(item.description, r.description),
        reverse=True,
    )
    best = scored[0]
    if _similarity(item.description, best.description) < 0.2:
        return None
    return best
