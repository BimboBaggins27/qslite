"""South African building-code reference shipped to the extraction LLM as context.

Brief, focused — covers the regulations a QS needs to flag in a quote so we
don't ship a quote missing legally required compliance items (CoCs, drip trays,
extractors, etc.). Not legal advice; reviewed against publicly published SANS
and NHBRC summaries.
"""
from __future__ import annotations


SA_BUILDING_CODES = """SOUTH AFRICAN BUILDING CODES — items required by regulation/standard. \
Include these as line items where the scope triggers them, otherwise the quote is \
incomplete and the contractor is exposed:

GENERAL — National Building Regulations (SANS 10400 series)
- All new building work in SA must comply with SANS 10400 parts (A-XA).
- NHBRC enrolment required for residential new-builds (not minor alterations).

ELECTRICAL — SANS 10142 / OHSA
- Any new circuit / DB change / fixed-appliance install MUST have an electrical \
  Certificate of Compliance (CoC) issued. Add as a P&G line: "Electrical CoC on \
  completion".
- Geyser install: requires isolator switch within 1m, drip tray plumbed to outside, \
  vacuum breakers on hot/cold inlets, expansion control valve, insulation blanket. \
  Each is a separate priceable line.

PLUMBING — SANS 10254 / SANS 10252
- New water installation requires a plumbing CoC (Certificate of Compliance) or \
  COC where a registered plumber signs off. Add as P&G line.
- Pressure test required on new pipework — separate hour-rate line.
- Backflow prevention required at municipal connection.

GEYSERS / SOLAR — SANS 10254 + SANS 10106
- Drip tray + overflow pipe outside, vacuum breakers, expansion control, isolator. \
  These are NOT optional; price them.

FIRE — SANS 10400-T
- Smoke alarms in residential bedroom corridors / escape routes (mandatory in new \
  residential).
- Hose reels / extinguishers in commercial per occupancy class.

VENTILATION — SANS 10400-O
- Internal bathrooms / WCs without external windows MUST have mechanical extraction. \
  Price an extractor fan + ducting line.
- Internal kitchens: extractor over stove with external venting.

ACCESSIBILITY — SANS 10400-S
- New public buildings need accessible ablution + ramp where applicable.

ENERGY EFFICIENCY — SANS 10400-XA
- Thermal insulation in roof spaces (R-value targets per climate zone).
- Hot water: ≥50% from non-resistive source OR equivalent SHGC compliance.
- Insulation on geyser + first 1m of hot pipe.

WATERPROOFING — manufacturer + SANS 10021
- Wet areas (showers, baths, balconies, flat roofs): waterproofing is a separate \
  trade from tiling. Price it.
- Edge protection / movement joints in tiling per SANS 10107.

DEMOLITION — SANS 10153 + municipal bylaws
- Permit may be required for demolitions over a threshold. Disposal at registered \
  landfill — price rubble removal accordingly.
- Asbestos identification and removal by registered contractor (where applicable).

OUTPUT GUIDANCE
- When the scope triggers any of the above, ADD the corresponding compliance items \
  as line items with their own rates. Use trade=`pgs` for certificates, `electrical` \
  for electrical-side compliance items, `plumbing` for plumbing-side, etc.
- If you're not sure whether a regulation applies, set confidence < 0.5 and \
  note "Compliance verification needed" in the line's notes.
"""


def codes_summary() -> str:
    return SA_BUILDING_CODES
