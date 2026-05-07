from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


Unit = Literal["m", "m2", "lin.m", "each", "kg", "hr", "no"]


class EditState(str, Enum):
    AI_SUGGESTED = "ai_suggested"
    USER_CONFIRMED = "user_confirmed"
    USER_EDITED = "user_edited"
    USER_ADDED = "user_added"


class Provenance(BaseModel):
    source_image: str = Field(description="Filename or ID of the source image")
    evidence: str = Field(description="What in the image supports this item — e.g. 'tiled wall, full height, north side'")
    bbox: Optional[str] = Field(
        default=None,
        description="Rough bounding-box description if the model gave one (e.g. 'centre-left, lower half')",
    )


class ExtractedItem(BaseModel):
    """Raw AI output — element recognised in the image, before rate matching."""

    description: str = Field(description="Natural-language description of the element/work")
    trade: str = Field(description="Trade group: tiling, painting, plumbing, electrical, carpentry, masonry, glazing, finishes, demolition, other")
    quantity: float = Field(gt=0, description="Numeric quantity, must be positive")
    unit: Unit
    zone: str = Field(default="Default", description="Zone or section the work belongs to (Kitchen, Bathroom 1, Exterior, etc.)")
    confidence: float = Field(ge=0, le=1, description="Model confidence 0-1")
    provenance: Provenance
    notes: Optional[str] = None
    rate_zar: Optional[float] = Field(default=None, description="AI-chosen unit rate in ZAR. Picked from catalogue or proposed for SA market.")
    rate_code: Optional[str] = Field(default=None, description="Catalogue rate code (e.g. 'TIL-001') if the AI used a catalogue match; None if the rate is freshly proposed.")


class ExtractionResult(BaseModel):
    items: list[ExtractedItem]
    overall_notes: Optional[str] = None
    suggested_subject: Optional[str] = None
    suggested_quote_name: Optional[str] = None


class ClarificationRequest(BaseModel):
    """Returned by the unified extractor when the AI is uncertain and wants user guidance.
    Carries a question + optional suggested options + a brief context summary."""

    question: str
    options: list[str] = Field(default_factory=list)
    context_so_far: str = ""


class Rate(BaseModel):
    """A unit rate from the catalogue."""

    code: str
    description: str
    trade: str
    unit: Unit
    rate_zar: float
    valid_from: str
    source: str = "internal-catalogue"

    def age_days(self, today: datetime | None = None) -> int:
        today = today or datetime.utcnow()
        valid = datetime.fromisoformat(self.valid_from)
        return (today - valid).days


class LineItem(BaseModel):
    """An item in a quote — links extracted info + rate + edit state."""

    id: str
    description: str
    trade: str
    quantity: float
    unit: Unit
    zone: str = "Default"
    rate_zar: float
    rate_code: Optional[str] = None
    rate_age_days: Optional[int] = None
    confidence: float
    provenance: Provenance
    state: EditState = EditState.AI_SUGGESTED
    notes: Optional[str] = None
    sanity_warnings: list[str] = Field(default_factory=list)
    high_value_review: bool = False

    @property
    def total_zar(self) -> float:
        return round(self.quantity * self.rate_zar, 2)

    @property
    def confidence_band(self) -> Literal["green", "amber", "red"]:
        if self.confidence >= 0.8:
            return "green"
        if self.confidence >= 0.5:
            return "amber"
        return "red"


class AuditEntry(BaseModel):
    ts: str
    actor: str
    action: str
    item_id: Optional[str] = None
    details: dict = Field(default_factory=dict)


class QuoteHeader(BaseModel):
    """Editable header fields shown on the issued quote document.

    Layout follows the Xero quotation/invoice pattern: company FROM block
    (top-left), big QUOTE badge with reference numbers (top-right), client
    BILL-TO block, line items, totals stack, banking footer, acceptance block.

    Defaults: company-side (your business) is pre-filled. Client-side and
    quote-specific fields are blank and reset between jobs.
    """

    # ----- Your company (persists across jobs) -----
    company_name: str = "NDLOVU T PROJECTS (Pty) Ltd"
    company_vat_reg: str = ""
    company_address: str = ""
    company_contact: str = ""

    # ----- Client (changes per job) -----
    client_name: str = ""
    client_vat_reg: str = ""
    client_address: str = ""
    attention: str = ""

    # ----- Quote-specific (changes per job) -----
    quote_no: str = ""
    quote_name: str = ""           # internal label, e.g. "Pool refurb — Building 1"
    quote_date: str = ""
    expiry_date: str = ""
    project_reference: str = ""
    re_subject: str = ""            # filled by AI from scope, or by the user
    project: str = ""               # project grouping label
    labels: str = ""                # comma-separated tags

    # ----- Persistent defaults (rarely change) -----
    payment_terms: str = "75% Deposit\n25% on Completion"
    banking_details: str = ""
    acceptance_block: str = "I accept this quotation as binding on behalf of the client.\n\nSigned: ____________________   Date: __________"
    vat_pct: float = 15.0
    show_vat: bool = False
    notes: str = ""

    @staticmethod
    def per_job_fields() -> list[str]:
        """Fields that should reset between jobs (when 'New job' is clicked)."""
        return [
            "client_name", "client_vat_reg", "client_address", "attention",
            "quote_no", "quote_name", "quote_date", "expiry_date",
            "project_reference", "re_subject", "project", "labels",
            "notes",
        ]
