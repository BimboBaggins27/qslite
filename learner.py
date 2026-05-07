"""Learning layer: predicts user adjustments and surfaces similar past jobs.

The learner is intentionally interpretable — every prediction is grounded in a
visible sample size and timestamped history. Predictions are *applied* to AI-
suggested items pre-confirm so the user starts from their typical correction
rather than the raw catalogue value, but every change is annotated and remains
soft-locked until the user confirms.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from typing import Optional

import memory
from schema import EditState, LineItem


MIN_SAMPLES_FOR_PREDICTION = 2
DAMPING = 0.7  # apply 70% of the historical median delta — conservative


# ---------- rate / quantity prediction ----------

def predict_rate_delta(rate_code: str) -> Optional[tuple[float, int]]:
    """Return (median_delta_pct, sample_size) or None if not enough data."""
    rows = memory.rate_edit_history(rate_code, limit=50)
    if len(rows) < MIN_SAMPLES_FOR_PREDICTION:
        return None
    deltas = [r["delta_pct"] for r in rows]
    return statistics.median(deltas), len(deltas)


def predict_qty_delta(rate_code: str) -> Optional[tuple[float, int]]:
    rows = memory.qty_edit_history(rate_code, limit=50)
    if len(rows) < MIN_SAMPLES_FOR_PREDICTION:
        return None
    deltas = [r["delta_pct"] for r in rows]
    return statistics.median(deltas), len(deltas)


def apply_predictions(items: list[LineItem]) -> list[tuple[LineItem, list[str]]]:
    """For each AI-suggested item, apply learned adjustments and return the
    annotated result. The returned list pairs each item with an ordered list of
    human-readable hints describing what the learner did and why."""
    out: list[tuple[LineItem, list[str]]] = []
    for li in items:
        hints: list[str] = []
        if li.state != EditState.AI_SUGGESTED or not li.rate_code:
            out.append((li, hints))
            continue

        # Rate prediction
        rp = predict_rate_delta(li.rate_code)
        if rp:
            delta, n = rp
            adjusted = round(li.rate_zar * (1 + delta * DAMPING), 2)
            if abs(adjusted - li.rate_zar) >= 1.0:
                pct = delta * DAMPING * 100
                hints.append(
                    f"💡 Rate auto-adjusted {pct:+.1f}% based on {n} past edits to {li.rate_code} "
                    f"(R {li.rate_zar:,.2f} → R {adjusted:,.2f}). Confirm or override."
                )
                li.rate_zar = adjusted

        # Quantity prediction
        qp = predict_qty_delta(li.rate_code)
        if qp:
            delta, n = qp
            adjusted = round(li.quantity * (1 + delta * DAMPING), 2)
            if abs(adjusted - li.quantity) >= 0.05:
                pct = delta * DAMPING * 100
                hints.append(
                    f"💡 Quantity auto-adjusted {pct:+.1f}% based on {n} past edits "
                    f"({li.quantity:.2f} → {adjusted:.2f} {li.unit}). Confirm or override."
                )
                li.quantity = adjusted

        out.append((li, hints))
    return out


# ---------- drift detection ----------

DRIFT_THRESHOLD_PCT = 0.10
DRIFT_MIN_SAMPLES = 3


def drifting_rate_codes() -> list[dict]:
    """Rate codes where the median user adjustment exceeds the drift threshold.

    These are catalogue rates that are likely systemically wrong (or stale) and
    should be reviewed by a human."""
    flagged = []
    for agg in memory.rate_edit_aggregates():
        if agg["n"] < DRIFT_MIN_SAMPLES:
            continue
        rows = memory.rate_edit_history(agg["rate_code"], limit=50)
        deltas = [r["delta_pct"] for r in rows]
        median = statistics.median(deltas)
        if abs(median) >= DRIFT_THRESHOLD_PCT:
            flagged.append({
                "rate_code": agg["rate_code"],
                "samples": agg["n"],
                "median_delta": median,
                "last_ts": agg["last_ts"],
            })
    return sorted(flagged, key=lambda f: -abs(f["median_delta"]))


# ---------- similar-job retrieval ----------

def _trade_vector(items: list[LineItem]) -> dict[str, float]:
    """Cheap signature: total ZAR per trade. Captures the shape of the job."""
    v: dict[str, float] = defaultdict(float)
    for li in items:
        v[li.trade] += li.total_zar
    total = sum(v.values()) or 1.0
    return {k: val / total for k, val in v.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def similar_quotes(items: list[LineItem], top_k: int = 3) -> list[dict]:
    """Find the most similar past issued quotes by trade-mix cosine similarity.

    Returns a list of dicts with: id, issued_at, total_zar, similarity, suggested_items
    (items present in the past quote that aren't already in the current draft, by
    rate_code, ranked by total_zar)."""
    if not items:
        return []

    current_vec = _trade_vector(items)
    current_codes = {li.rate_code for li in items if li.rate_code}

    past = memory.all_issued_quotes()
    if not past:
        return []

    scored = []
    for q in past:
        subs = json.loads(q["trade_subtotals"])
        total = sum(subs.values()) or 1.0
        past_vec = {k: v / total for k, v in subs.items()}
        sim = _cosine(current_vec, past_vec)
        if sim < 0.2:
            continue
        scored.append((sim, q))

    scored.sort(key=lambda x: -x[0])
    out: list[dict] = []
    for sim, q in scored[:top_k]:
        past_items = memory.items_for_quote(q["id"])
        suggested = [
            {
                "rate_code": pi["rate_code"],
                "trade": pi["trade"],
                "description": pi["description"],
                "quantity": pi["quantity"],
                "unit": pi["unit"],
                "rate_zar": pi["rate_zar"],
                "total_zar": pi["total_zar"],
            }
            for pi in past_items
            if pi["rate_code"] and pi["rate_code"] not in current_codes
        ]
        suggested.sort(key=lambda x: -x["total_zar"])
        out.append({
            "id": q["id"],
            "issued_at": q["issued_at"],
            "total_zar": q["total_zar"],
            "similarity": sim,
            "suggested_items": suggested[:5],
        })
    return out
