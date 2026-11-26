"""Language-neutral structured document model.

Every agent reads and writes this model; the Builder renders it. Nothing in
here is specific to a language pair: direction and language live on the
document and, where needed, on individual blocks and runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class Direction(str, Enum):
    ltr = "ltr"
    rtl = "rtl"


class BlockType(str, Enum):
    heading = "heading"
    paragraph = "paragraph"
    numbered_item = "numbered_item"
    bullet = "bullet"
    table = "table"
    kv_table = "kv_table"
    note = "note"                      # stamps, seals, signatures, photos ... rendered inside // //
    page_break = "page_break"
    signature_block = "signature_block"
    unreadable = "unreadable"


class BlockStatus(str, Enum):
    draft = "draft"
    translated = "translated"
    proofread = "proofread"
    qa_passed = "qa_passed"
    needs_review = "needs_review"
    approved = "approved"


class RunKind(str, Enum):
    text = "text"
    identifier = "identifier"   # ID / tax / serial / reference numbers, codes, hashes
    number = "number"
    date = "date"
    email = "email"
    url = "url"
    name = "name"


class UnreadableReason(str, Enum):
    illegible = "illegible"
    covered_by_stamp = "covered_by_stamp"
    truncated = "truncated"


class NoteKind(str, Enum):
    stamp = "stamp"
    seal = "seal"
    signature = "signature"
    hologram = "hologram"
    revenue_stamp = "revenue_stamp"
    barcode = "barcode"
    qr_code = "qr_code"
    logo = "logo"
    photo = "photo"
    handwriting = "handwriting"
    other = "other"


class Severity(str, Enum):
    blocker = "blocker"
    major = "major"
    minor = "minor"
    info = "info"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class InlineRun(_Base):
    """A piece of translated text. Non-`text` runs are isolated by the Builder
    (bidi isolation when they run against the paragraph direction)."""
    text: str
    kind: RunKind = RunKind.text
    direction: Optional[Direction] = None   # None = inferred from the characters
    bold: bool = False
    italic: bool = False


class Flag(_Base):
    code: str                               # e.g. "low_ocr_confidence", "number_mismatch"
    severity: Severity = Severity.minor
    message: str = ""
    agent: Optional[str] = None
    resolved: bool = False


class HistoryEntry(_Base):
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str                              # agent name or user id
    field: str = "translated_text"
    old: Optional[str] = None
    new: Optional[str] = None
    reason: str = ""


class TableCell(_Base):
    source_text: str = ""
    translated_text: str = ""
    runs: Optional[list[InlineRun]] = None
    header: bool = False
    colspan: int = 1
    bold: bool = False


class TableRow(_Base):
    cells: list[TableCell]
    header: bool = False


class Layout(_Base):
    """Formatter output: presentation hints only, never content."""
    align: Optional[Literal["start", "center", "end", "justify"]] = None
    bold: Optional[bool] = None
    font_scale: float = 1.0                 # relative to profile body size
    keep_with_next: bool = False
    space_before_pt: Optional[float] = None
    space_after_pt: Optional[float] = None
    indent_level: int = 0


class Block(_Base):
    id: str
    type: BlockType
    source_page: Optional[int] = None       # 1-based page in the source document
    source_text: str = ""
    translated_text: str = ""
    runs: Optional[list[InlineRun]] = None  # if absent, the Builder segments translated_text
    direction: Optional[Direction] = None   # None = document target direction
    status: BlockStatus = BlockStatus.draft
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    flags: list[Flag] = Field(default_factory=list)
    history: list[HistoryEntry] = Field(default_factory=list)
    layout: Layout = Field(default_factory=Layout)

    # type-specific
    level: int = Field(1, ge=1, le=6)                       # heading
    label: Optional[str] = None                             # numbered_item label as in source ("1.", "(a)", "IV")
    rows: list[TableRow] = Field(default_factory=list)      # table / kv_table
    column_widths: Optional[list[float]] = None             # relative widths
    note_kind: Optional[NoteKind] = None                    # note
    note_scope: Literal["inline", "page_end", "document_end"] = "inline"
    unreadable_reason: Optional[UnreadableReason] = None    # unreadable
    multilingual_duplicate: bool = False                    # source repeated in several languages, translated once

    @model_validator(mode="after")
    def _check_type_fields(self) -> "Block":
        if self.type in (BlockType.table, BlockType.kv_table) and not self.rows:
            raise ValueError(f"block {self.id}: {self.type.value} needs rows")
        if self.type == BlockType.kv_table:
            for r in self.rows:
                if len(r.cells) != 2:
                    raise ValueError(f"block {self.id}: kv_table rows need exactly 2 cells")
        if self.type == BlockType.unreadable and self.unreadable_reason is None:
            raise ValueError(f"block {self.id}: unreadable needs unreadable_reason")
        if self.column_widths is not None and self.rows:
            ncols = max(sum(c.colspan for c in r.cells) for r in self.rows)
            if len(self.column_widths) != ncols:
                raise ValueError(f"block {self.id}: column_widths length {len(self.column_widths)} != {ncols} columns")
        return self


class PageInfo(_Base):
    number: int
    languages: list[str] = Field(default_factory=list)
    orientation: Literal["portrait", "landscape"] = "portrait"
    rotation: int = 0                       # degrees needed to bring the page upright
    has_stamp: bool = False
    has_signature: bool = False
    has_handwriting: bool = False
    has_table: bool = False
    ocr_confidence: Optional[float] = None


class GlossaryEntry(_Base):
    source: str
    target: str
    kind: Literal["name", "acronym", "term", "organisation", "place"] = "term"
    confirmed: bool = False


class Document(_Base):
    schema_version: str = SCHEMA_VERSION
    id: str
    title: str
    source_language: str                    # profile code, e.g. "en", "ar", "fr"
    target_language: str
    document_type: Optional[str] = None
    pages: list[PageInfo] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    blocks: list[Block]

    @model_validator(mode="after")
    def _unique_ids(self) -> "Document":
        seen: set[str] = set()
        for b in self.blocks:
            if b.id in seen:
                raise ValueError(f"duplicate block id {b.id}")
            seen.add(b.id)
        if self.source_language == self.target_language:
            raise ValueError("source_language and target_language must differ")
        return self

    def json_schema(self) -> dict:  # pragma: no cover - convenience
        return Document.model_json_schema()


# --------------------------------------------------------------------------- job

class StampChoice(str, Enum):
    certified = "certified"   # translator's personal certified stamp
    office = "office"         # company stamp


class PageOrder(str, Enum):
    translation_then_source = "translation_then_source"
    interleaved = "interleaved"


class JobSpec(_Base):
    """Per-job settings. `stamp` is required with no default: a job cannot
    start until the user has chosen one."""
    stamp: StampChoice
    user_id: str
    template_id: Optional[str] = None
    pdf_page_order: PageOrder = PageOrder.translation_then_source
    notes: Optional[str] = None
