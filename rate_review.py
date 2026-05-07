"""Rate review queue + bulk uplift.

Two signals push a rate into the review queue:
1. Rate is older than `STALE_DAYS` (default 90).
2. Rate is "drifting" — median user adjustment crosses ±10% threshold.

Bulk uplift writes back to data/rates.json with a today timestamp on touched rates.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import learner
from rates import RATES_PATH, load_rates
from schema import Rate


STALE_DAYS = 90


def review_queue(stale_days: int = STALE_DAYS) -> list[dict]:
    """Return one row per rate, marked stale and/or drifting where applicable.
    Rows that are neither are filtered out. Sorted by impact (drift mag, then age)."""
    drift_map = {d["rate_code"]: d for d in learner.drifting_rate_codes()}
    today = datetime.utcnow()

    out = []
    for r in load_rates():
        age = r.age_days(today)
        is_stale = age >= stale_days
        drift = drift_map.get(r.code)
        if not (is_stale or drift):
            continue
        out.append({
            "code": r.code,
            "description": r.description,
            "trade": r.trade,
            "unit": r.unit,
            "rate_zar": r.rate_zar,
            "valid_from": r.valid_from,
            "age_days": age,
            "stale": is_stale,
            "drift_pct": drift["median_delta"] if drift else None,
            "drift_samples": drift["samples"] if drift else None,
        })

    out.sort(key=lambda r: (-(abs(r["drift_pct"]) if r["drift_pct"] else 0), -r["age_days"]))
    return out


def apply_bulk_uplift(trade: Optional[str], pct: float, only_stale: bool = True) -> int:
    """Apply +pct% to every rate matching the filter. Update valid_from to today.
    Returns the number of rates updated."""
    raw = json.loads(RATES_PATH.read_text(encoding="utf-8"))
    today_iso = datetime.utcnow().date().isoformat()
    today = datetime.utcnow()
    n = 0
    for r in raw:
        if trade and r["trade"].lower() != trade.lower():
            continue
        if only_stale:
            valid = datetime.fromisoformat(r["valid_from"])
            age = (today - valid).days
            if age < STALE_DAYS:
                continue
        r["rate_zar"] = round(r["rate_zar"] * (1 + pct), 2)
        r["valid_from"] = today_iso
        n += 1
    RATES_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    load_rates.cache_clear()  # type: ignore[attr-defined]
    return n


def apply_one_uplift(rate_code: str, new_rate: float) -> bool:
    """Manually overwrite a single rate. Updates valid_from to today."""
    raw = json.loads(RATES_PATH.read_text(encoding="utf-8"))
    today_iso = datetime.utcnow().date().isoformat()
    for r in raw:
        if r["code"] == rate_code:
            r["rate_zar"] = round(new_rate, 2)
            r["valid_from"] = today_iso
            RATES_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            load_rates.cache_clear()  # type: ignore[attr-defined]
            return True
    return False
