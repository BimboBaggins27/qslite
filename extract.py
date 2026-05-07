from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Optional

import anthropic

from schema import ClarificationRequest, ExtractedItem, ExtractionResult, Provenance

MODEL = "claude-sonnet-4-5"

def _catalogue_summary() -> str:
    """One-line summary per catalogue rate, fed to the model so it can pick or propose rates accurately."""
    from rates import load_rates
    lines = ["RATE CATALOGUE (use rate_code when a clear match exists; pick the rate from this list — do NOT mismatch):"]
    for r in load_rates():
        lines.append(f"  {r.code} | {r.trade} | {r.unit} | R{r.rate_zar:,.2f} | {r.description}")
    return "\n".join(lines)


def _prompt_with_catalogue(base: str) -> str:
    """Append the rate catalogue + SA building codes so every extraction call has them as context."""
    from building_codes import codes_summary
    return base.rstrip() + "\n\n" + _catalogue_summary() + "\n\n" + codes_summary()


SYSTEM_PROMPT_BASE = """You are an expert quantity surveyor (QS) AI. Your job is to look at construction \
photos, drawings, or scanned plans and break them down into discrete buildable elements that can \
be priced as line items in a quotation.

THINK HOLISTICALLY. Real quotations include not only the visibly-named element but the \
preparation, supply, install, and finishing items needed to complete that element as a \
buildable unit. For example: if you see a new drywall, also include paint prep, plaster primer, \
two coats of PVA, skirting, and any door/window-opening work needed to make it functional. If you \
see new tiling, include adhesive, grout, edge trims, and waterproofing where appropriate. If you \
see plumbing fixtures, include the connection / supply line work. Use "extra over" line items \
where appropriate (corners, abutments, openings, special fittings). Group everything under the \
correct zone (room/area).

QUOTE QUALITY RULES — these are non-negotiable:
1. **CONCISE descriptions** — 5-12 words each. No redundant phrasing. e.g. "Wall tiling, ceramic 300x600, supply and fix" NOT "Floor/wall tiling supply and install with adhesive and grout, leave expansion joints (where applicable)".
2. **NO DUPLICATES** — never emit two line items for the same work. If the same item spans two areas, sum the quantity into ONE line.
3. **PRICE EVERY LINE** — set `rate_zar` for every item. Use the catalogue when there's a clear match; PROPOSE a fair affordable SA-market rate when there isn't. Set `rate_code` only when you used a catalogue entry.
4. **MATCH RATES TO WORK** — never assign a rate that obviously belongs to a different trade (e.g. don't price paving at the brick-wall rate). Verify trade + unit alignment.
5. **GROUP UNDER ZONES** — every item in the right zone. Don't put painting items in a "Painting" zone — put them in the room they're painting.
6. **ONLY VISIBLE WORK** + the standard prep/finishes that make it complete. No imaginary scope.

For each element you identify in the image you MUST output:
- description: short natural-language description of the work (e.g. "Wall tiling, full height")
- trade: one of [drywall, tiling, painting, plumbing, electrical, carpentry, masonry, glazing, finishes, demolition, pgs, other]
- quantity: a positive number — your best estimate based on visible scale, references, or stated dimensions
- unit: one of [m, m2, lin.m, each, kg, hr, no]
- zone: short label for the room/section the work is in (e.g. "Bathroom", "Kitchen", "Master bedroom", "Exterior"). Use the user-supplied context if provided. Default to "Default" if truly unidentifiable.
- confidence: 0-1 — be honest. If you're guessing because there's no scale reference, drop below 0.5.
- provenance: { source_image, evidence, bbox } — what in the image supports this item
- notes: optional caveats (e.g. "scale assumed from standard door height of 2.0m")

CRITICAL RULES
1. Never invent items not visibly present.
2. If you cannot estimate a quantity reliably (no scale, no dimensions), still include the item but \
set confidence < 0.4 and explain in notes.
3. Use SI units only. m2 (not sqm), lin.m (not lm), each (not ea).
4. Walls are typically 2.7m high in residential SA unless drawing says otherwise. State assumptions in notes.
5. Output strict JSON conforming to the schema. No prose outside JSON.
"""

EXTRACTION_TOOL = {
    "name": "record_extracted_elements",
    "description": "Record the buildable elements you have identified in the image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "trade": {
                            "type": "string",
                            "enum": [
                                "drywall", "tiling", "painting", "plumbing", "electrical",
                                "carpentry", "masonry", "glazing", "finishes",
                                "demolition", "pgs", "other",
                            ],
                        },
                        "quantity": {"type": "number", "exclusiveMinimum": 0},
                        "unit": {
                            "type": "string",
                            "enum": ["m", "m2", "lin.m", "each", "kg", "hr", "no"],
                        },
                        "zone": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "provenance": {
                            "type": "object",
                            "properties": {
                                "source_image": {"type": "string"},
                                "evidence": {"type": "string"},
                                "bbox": {"type": "string"},
                            },
                            "required": ["source_image", "evidence"],
                        },
                        "notes": {"type": "string"},
                        "rate_zar": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Unit rate in ZAR for this item. PICK FROM THE CATALOGUE if there's a clear match; otherwise PROPOSE an affordable SA-market rate. Always include this — it's required so the user gets a costed line out of the box.",
                        },
                        "rate_code": {
                            "type": "string",
                            "description": "Set ONLY when you used a catalogue rate (e.g. 'TIL-001'). Leave empty for freshly proposed rates.",
                        },
                    },
                    "required": [
                        "description", "trade", "quantity", "unit",
                        "confidence", "provenance", "rate_zar",
                    ],
                },
            },
            "overall_notes": {"type": "string"},
            "suggested_subject": {
                "type": "string",
                "description": "A short, professional 'RE:' subject line summarising the scope of work in the quote. Examples: 'Proposed pool area refurbishment to Building 1 MBP', 'Master bathroom strip-out and refit', 'Drywall partitioning to office floor 3'. Use the actual scope visible in the inputs — do NOT default to drywall or any single trade.",
            },
            "suggested_quote_name": {
                "type": "string",
                "description": "Short internal label for this quote, 3-6 words. e.g. 'Pool refurb — Building 1', 'Master bath refit'.",
            },
        },
        "required": ["items"],
    },
}


_TARGET_BYTES = 4 * 1024 * 1024  # 4 MB — keep well under Anthropic's 5 MB-per-image limit


def _normalize_image_for_vision(image_bytes: bytes, media_type: str, max_edge: int = 2400) -> tuple[bytes, str]:
    """Ensure image is within Claude's vision limits — both pixel dimensions AND byte size.
    Strategy:
      1. Resize so longest edge <= max_edge (Claude's vision sweet spot ~1568-2400 px).
      2. Try saving as PNG first (best for line art / drawings).
      3. If PNG > 4 MB, fall back to JPEG at quality 85 → 70 → 55, halving max_edge if still too big.
    Anthropic rejects any image > 5 MB after base64, hence the 4 MB target with safety margin.
    """
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(image_bytes))
        # Strip alpha for JPEG path
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode != "RGB":
                try:
                    background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
                    img = background
                except Exception:
                    img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Initial resize for pixel dimensions
        w, h = img.size
        long_edge = max(w, h)
        target = None
        if long_edge > max_edge:
            target = max_edge
        elif long_edge < 800:
            target = 1600  # upscale small inputs so the model can read text annotations
        if target:
            scale = target / long_edge
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # Try PNG first — best for drawings / line art
        buf = _io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png_bytes = buf.getvalue()
        if len(png_bytes) <= _TARGET_BYTES:
            return png_bytes, "image/png"

        # Too big as PNG → progressively try JPEG at descending quality + size
        for current_max_edge in (max_edge, int(max_edge * 0.75), int(max_edge * 0.55)):
            cur = img
            cw, ch = cur.size
            cur_long = max(cw, ch)
            if cur_long > current_max_edge:
                scale = current_max_edge / cur_long
                cur = cur.resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
            for q in (85, 75, 65, 55):
                jb = _io.BytesIO()
                cur.save(jb, format="JPEG", quality=q, optimize=True, progressive=True)
                data = jb.getvalue()
                if len(data) <= _TARGET_BYTES:
                    return data, "image/jpeg"
        # Last-resort: emit smallest JPEG we can
        return data, "image/jpeg"
    except Exception:
        return image_bytes, media_type


def _image_to_block(image_bytes: bytes, media_type: str, normalize: bool = True) -> dict:
    if normalize:
        image_bytes, media_type = _normalize_image_for_vision(image_bytes, media_type)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
        },
    }


def extract_elements(
    image_bytes: bytes,
    media_type: str,
    image_filename: str,
    extra_context: Optional[str] = None,
) -> ExtractionResult:
    """Run the vision LLM and return structured ExtractionResult."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    user_text = (
        f"Image filename: {image_filename}\n"
        "Identify every priceable element you see and return it via the tool. "
        "Use the filename above as the `provenance.source_image` for every item."
    )
    if extra_context:
        user_text += f"\n\nUser-supplied context:\n{extra_context}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=_prompt_with_catalogue(SYSTEM_PROMPT_BASE),
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_extracted_elements"},
        messages=[
            {
                "role": "user",
                "content": [
                    _image_to_block(image_bytes, media_type),
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )

    tool_use = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if tool_use is None:
        raise RuntimeError("Model did not return a tool_use block")

    raw = tool_use.input
    items = []
    for it in raw.get("items", []):
        prov = it["provenance"]
        items.append(
            ExtractedItem(
                description=it["description"],
                trade=it["trade"],
                quantity=it["quantity"],
                unit=it["unit"],
                zone=it.get("zone") or "Default",
                confidence=it["confidence"],
                provenance=Provenance(
                    source_image=prov.get("source_image", image_filename),
                    evidence=prov.get("evidence", ""),
                    bbox=prov.get("bbox"),
                ),
                notes=it.get("notes"),
                rate_zar=it.get("rate_zar"),
                rate_code=(it.get("rate_code") or None) or None,
            )
        )
    return ExtractionResult(items=items, overall_notes=raw.get("overall_notes"), suggested_subject=raw.get("suggested_subject"), suggested_quote_name=raw.get("suggested_quote_name"))


ASK_CLARIFICATION_TOOL = {
    "name": "ask_clarification",
    "description": (
        "Use this when the input is ambiguous, contradictory, or you can't proceed without "
        "user guidance. Return a specific question and 2-5 suggested short answer options the "
        "user can click. Prefer asking over guessing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Specific question to the user."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 short suggested answer options the user can pick.",
            },
            "context_so_far": {
                "type": "string",
                "description": "One-sentence summary of what you understood from the inputs.",
            },
        },
        "required": ["question"],
    },
}


UNIFIED_SYSTEM_PROMPT = """You are an expert quantity surveyor (QS) AI working through a single \
input channel. The user uploads any combination of photos, drawings, scanned plans, PDFs (one or \
many) plus an optional text context. YOU decide what to do:

- **One file**: standard QS take-off via record_extracted_elements.
- **Two files that look like EXISTING vs PROPOSED** (judging from filenames/content/context): produce \
  a delta BOQ. Prefix descriptions with `[REMOVE]`, `[NEW]`, or `[MODIFY]`. Use trade=`demolition` \
  for removals.
- **Multiple unrelated files**: aggregate into one BOQ, zone-tag each item.
- **Ambiguous, contradictory, or you genuinely don't know what to do**: use ask_clarification with a \
  specific question and 2-5 short answer options.

NEVER throw an error or refuse. NEVER fabricate items you can't see. If stuck, ASK.

Think holistically: for any visible work, include preparation, supply, install, and finishing items \
needed to complete it as a buildable unit. Include extra-overs (corners, abutments, openings).

QUOTE QUALITY RULES — non-negotiable:
1. CONCISE descriptions — 5-12 words. No verbose phrasing.
2. NO DUPLICATES — sum quantities into one line if the same item recurs.
3. PRICE EVERY LINE — set rate_zar for every item. Use rate_code only when you matched the catalogue.
4. NEVER mismatch rates to trades (e.g. paving must NOT get a brick-wall rate).
5. Group items under the right ZONE (room/area), not by trade.
6. Set suggested_subject (RE: line) and suggested_quote_name from the actual scope.

VISUAL INSPECTION CHECKLIST — work through this BEFORE listing line items:
A. Scan ALL written text on the drawing/photo: dimensions (e.g. "3750mm", "21m", "2.4m"), \
   scale references, room labels, material callouts, notes. Report what you read in overall_notes.
B. Identify the SCALE of the drawing — explicitly. If a scale bar or dimension reference exists, \
   anchor your quantities to it. If none exists, state the assumption (e.g. "scale assumed from \
   standard 0.9m door width") in the line's notes and drop confidence to 0.5 or lower.
C. Look for COMPLIANCE CUES in the drawing: extractor fans, drip trays, isolators, smoke alarms, \
   waterproofing layers, accessibility ramps. If a regulation triggers but the drawing doesn't \
   show it, ADD the compliance line item anyway (it's required by code).
D. Cross-check measured dimensions against typical residential SA: walls ~2.7m high, doors \
   2.0m × 0.9m, ceilings 2.4-3.0m, kitchen units ~600mm deep. Anything wildly off → flag in notes.

Output strict JSON via tools — no prose outside tool calls.
"""


def extract_unified(
    inputs: list[tuple[bytes, str, str]],
    extra_context: Optional[str] = None,
) -> ExtractionResult | ClarificationRequest:
    """One-channel extractor. Inputs is a list of (bytes, media_type, filename).
    PDFs are auto-rendered to first-page PNGs; multi-page PDFs are flattened to one
    representative page each. Returns either an ExtractionResult or a ClarificationRequest."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    content_blocks: list[dict] = []
    file_summary_lines: list[str] = []
    for raw_bytes, media, fname in inputs:
        is_pdf = media == "application/pdf" or fname.lower().endswith(".pdf")
        if is_pdf:
            try:
                pages = pdf_pages_to_pngs(raw_bytes, scale=3.0)
            except Exception as e:
                file_summary_lines.append(f"- {fname}: PDF render failed ({e})")
                continue
            for i, (label, png) in enumerate(pages):
                content_blocks.append(_image_to_block(png, "image/png"))
                file_summary_lines.append(f"- {fname} ({label})")
        else:
            content_blocks.append(_image_to_block(raw_bytes, media or "image/jpeg"))
            file_summary_lines.append(f"- {fname}")

    user_text = f"Files attached ({len(file_summary_lines)} pages/images):\n" + "\n".join(file_summary_lines)
    if extra_context:
        user_text += f"\n\nUser context:\n{extra_context}"
    user_text += (
        "\n\nFirst, read every dimension annotation, scale reference, and text label visible "
        "in the inputs and capture them in overall_notes. THEN decide: extract elements "
        "(record_extracted_elements) or ask for guidance (ask_clarification). Do not skip the "
        "text-reading step — quantities anchored to actual visible dimensions are far more useful."
    )
    content_blocks.append({"type": "text", "text": user_text})

    response = client.messages.create(
        model=MODEL,
        max_tokens=16384,
        system=_prompt_with_catalogue(UNIFIED_SYSTEM_PROMPT),
        tools=[EXTRACTION_TOOL, ASK_CLARIFICATION_TOOL],
        messages=[{"role": "user", "content": content_blocks}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        return ClarificationRequest(
            question="I couldn't decide what to do with the input. What would you like me to extract?",
            options=["Just list everything visible", "Compare two drawings", "Try again with more context"],
        )

    if tool_use.name == "ask_clarification":
        raw = tool_use.input
        return ClarificationRequest(
            question=str(raw.get("question") or "What would you like me to do?"),
            options=list(raw.get("options") or []),
            context_so_far=str(raw.get("context_so_far") or ""),
        )

    # extraction path
    raw = tool_use.input
    items = []
    for it in raw.get("items", []):
        prov = it.get("provenance") or {}
        items.append(
            ExtractedItem(
                description=it["description"],
                trade=it["trade"],
                quantity=it["quantity"],
                unit=it["unit"],
                zone=it.get("zone") or "Default",
                confidence=it["confidence"],
                provenance=Provenance(
                    source_image=prov.get("source_image", inputs[0][2] if inputs else "unknown"),
                    evidence=prov.get("evidence", ""),
                    bbox=prov.get("bbox"),
                ),
                notes=it.get("notes"),
                rate_zar=it.get("rate_zar"),
                rate_code=(it.get("rate_code") or None) or None,
            )
        )
    return ExtractionResult(items=items, overall_notes=raw.get("overall_notes"), suggested_subject=raw.get("suggested_subject"), suggested_quote_name=raw.get("suggested_quote_name"))


def pdf_pages_to_pngs(pdf_bytes: bytes, scale: float = 2.0) -> list[tuple[str, bytes]]:
    """Render every page of a PDF to PNG. Returns [(page_label, png_bytes), ...]."""
    import pypdfium2 as pdfium

    out: list[tuple[str, bytes]] = []
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        for i, page in enumerate(pdf, start=1):
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            out.append((f"page-{i}", buf.getvalue()))
    finally:
        pdf.close()
    return out


DIFF_SYSTEM_PROMPT = """You are an expert quantity surveyor (QS) AI doing a comparative \
take-off between two construction drawings or photos: an EXISTING / as-built drawing and a \
PROPOSED / new drawing.

Your task: identify everything that needs to happen on site to go FROM existing TO proposed. \
Output a single combined list of buildable line items covering:
- DEMOLITION / strip-out for elements present in EXISTING but absent in PROPOSED
- NEW SUPPLY-AND-INSTALL for elements absent in EXISTING but present in PROPOSED
- MODIFICATION line items where an element is reshaped, rerouted, or upgraded (treat as remove + new)

Each line item must include:
- description: prefixed with [REMOVE], [NEW], or [MODIFY] so it's unambiguous
- trade: use "demolition" for removals; the appropriate trade for new work
- quantity, unit, zone, confidence, provenance, notes
- For removals, set provenance.evidence to "present in EXISTING, absent in PROPOSED"
- For new work, set provenance.evidence to "absent in EXISTING, present in PROPOSED"

Think holistically about the consequences of changes. If a wall is removed, also remove its \
finishes (paint, skirting, tiles). If a new wall is added, include painting, skirting, paint prep. \
If plumbing is rerouted, include both the demolition of the old route and supply+install of the \
new route plus making good wall finishes.

CRITICAL: Use the same JSON schema as a normal extraction (the record_extracted_elements tool). \
Be honest about confidence — if something might be a graphical artifact rather than a real change, \
set confidence below 0.5.
"""


def extract_diff_from_drawings(
    existing_bytes: bytes,
    existing_media: str,
    existing_filename: str,
    proposed_bytes: bytes,
    proposed_media: str,
    proposed_filename: str,
    extra_context: Optional[str] = None,
) -> ExtractionResult:
    """Compare an EXISTING drawing/photo to a PROPOSED one and return the BOQ delta as line items
    with [REMOVE]/[NEW]/[MODIFY] prefixes."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    user_text = (
        f"EXISTING drawing filename: {existing_filename}\n"
        f"PROPOSED drawing filename: {proposed_filename}\n"
        "Image 1 below is the EXISTING drawing. Image 2 is the PROPOSED drawing. "
        "Identify the delta and return it via the tool. Use the EXISTING filename in provenance "
        "for [REMOVE] items, and the PROPOSED filename for [NEW]/[MODIFY] items."
    )
    if extra_context:
        user_text += f"\n\nUser-supplied context:\n{extra_context}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=16384,
        system=_prompt_with_catalogue(DIFF_SYSTEM_PROMPT),
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_extracted_elements"},
        messages=[
            {
                "role": "user",
                "content": [
                    _image_to_block(existing_bytes, existing_media),
                    _image_to_block(proposed_bytes, proposed_media),
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise RuntimeError("Model did not return a tool_use block")

    raw = tool_use.input
    items = []
    for it in raw.get("items", []):
        prov = it["provenance"]
        items.append(
            ExtractedItem(
                description=it["description"],
                trade=it["trade"],
                quantity=it["quantity"],
                unit=it["unit"],
                zone=it.get("zone") or "Default",
                confidence=it["confidence"],
                provenance=Provenance(
                    source_image=prov.get("source_image", proposed_filename),
                    evidence=prov.get("evidence", ""),
                    bbox=prov.get("bbox"),
                ),
                notes=it.get("notes"),
                rate_zar=it.get("rate_zar"),
                rate_code=(it.get("rate_code") or None) or None,
            )
        )
    return ExtractionResult(items=items, overall_notes=raw.get("overall_notes"), suggested_subject=raw.get("suggested_subject"), suggested_quote_name=raw.get("suggested_quote_name"))


def _bytes_to_png(b: bytes, media_type: str, filename: str) -> tuple[bytes, str]:
    """Normalize input — render PDFs to first-page PNG; pass through images unchanged.
    Returns (png_or_image_bytes, media_type)."""
    is_pdf = media_type == "application/pdf" or filename.lower().endswith(".pdf")
    if is_pdf:
        pages = pdf_pages_to_pngs(b, scale=2.0)
        if not pages:
            raise RuntimeError(f"Could not render PDF: {filename}")
        return pages[0][1], "image/png"
    return b, media_type or "image/jpeg"


def extract_diff_from_files(
    existing_bytes: bytes,
    existing_media: str,
    existing_filename: str,
    proposed_bytes: bytes,
    proposed_media: str,
    proposed_filename: str,
    extra_context: Optional[str] = None,
) -> ExtractionResult:
    """Convenience wrapper: accept either images or PDFs; convert PDFs to first-page PNGs and call extract_diff_from_drawings."""
    e_b, e_m = _bytes_to_png(existing_bytes, existing_media, existing_filename)
    p_b, p_m = _bytes_to_png(proposed_bytes, proposed_media, proposed_filename)
    return extract_diff_from_drawings(
        e_b, e_m, existing_filename,
        p_b, p_m, proposed_filename,
        extra_context=extra_context,
    )


def extract_elements_from_pdf(
    pdf_bytes: bytes,
    pdf_filename: str,
    extra_context: Optional[str] = None,
) -> ExtractionResult:
    """Render each page to PNG and run extraction per page; merge the results.
    Per-page failures are caught and reported in `overall_notes` rather than aborting the whole PDF."""
    pages = pdf_pages_to_pngs(pdf_bytes)
    all_items = []
    notes = []
    for page_label, png in pages:
        page_filename = f"{pdf_filename}#{page_label}"
        page_context = (extra_context or "")
        if page_context:
            page_context += "\n"
        page_context += f"This is {page_label} of the PDF '{pdf_filename}'."
        try:
            result = extract_elements(png, "image/png", page_filename, extra_context=page_context)
        except Exception as e:
            notes.append(f"{page_label}: extraction failed — {type(e).__name__}: {e}")
            continue
        all_items.extend(result.items)
        if result.overall_notes:
            notes.append(f"{page_label}: {result.overall_notes}")
    return ExtractionResult(items=all_items, overall_notes="\n".join(notes) or None)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python extract.py <image-path>")
        sys.exit(1)
    p = Path(sys.argv[1])
    media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    result = extract_elements(p.read_bytes(), media, p.name)
    print(json.dumps(result.model_dump(), indent=2))
