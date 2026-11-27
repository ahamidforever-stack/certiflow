"""Agent output contracts (structured outputs; flat, non-recursive schemas).

Agents never return the Document model itself. They return these small
contracts and code applies them to the model, recording history on every
block they touch.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

SrcType = Literal["heading", "paragraph", "numbered_item", "bullet", "table", "kv_table", "note",
                  "signature_block", "unreadable"]
NoteKind = Literal["stamp", "seal", "signature", "hologram", "revenue_stamp", "barcode", "qr_code", "logo",
                   "photo", "handwriting", "other"]
Severity = Literal["blocker", "major", "minor"]


# ------------------------------------------------------------------ intake

class SourceBlockOut(BaseModel):
    type: SrcType
    level: Optional[int]                     # heading level 1-3
    label: Optional[str]                     # list label exactly as in the source ("1.", "(a)", "IV")
    text: str                                # source text exactly as written (empty for tables)
    rows: Optional[list[list[str]]]          # table cells as written; kv_table: [label, value, (label, value)...]
    header_row: bool                         # first table row is a header
    note_kind: Optional[NoteKind]
    note_description: Optional[str]          # notes: what it is, legible text, numbers, colour, shape (in English)
    unreadable_reason: Optional[Literal["illegible", "covered_by_stamp", "truncated"]]
    confidence: float                        # 0-1 confidence in the reading
    continues_previous_page: bool            # sentence/paragraph split by the page break (join with previous)
    multilingual_duplicate: bool             # same text already given on this page in another language
    repeated_on_every_page: bool             # identical stamp/signature/header repeated across pages
    bbox: Optional[list[int]] = None         # [x0, y0, x1, y1] on a 0-1000 grid of the page image


class UncertainRegion(BaseModel):
    block_index: int                         # index into blocks
    bbox: list[int]                          # [x0, y0, x1, y1] on a 0-1000 grid of the page image
    reason: str


class IntakePageOut(BaseModel):
    languages: list[str]                     # ISO 639-1 codes present on the page
    rotation_needed: Literal[0, 90, 180, 270]
    has_stamp: bool
    has_signature: bool
    has_handwriting: bool
    has_table: bool
    removed_artifacts: list[str]             # page numbers, paper serial lines removed per the rules
    blocks: list[SourceBlockOut]
    uncertain_regions: list[UncertainRegion]


class ZoomOut(BaseModel):
    text: str                                # best reading of the crop, exactly as written
    legible: bool
    covered_by_stamp: bool
    confidence: float


# ---------------------------------------------------------------- glossary

class GlossaryItem(BaseModel):
    source: str
    target: str
    kind: Literal["name", "acronym", "term", "organisation", "place"]
    note: Optional[str]


class GlossaryOut(BaseModel):
    items: list[GlossaryItem]


# -------------------------------------------------------------- translator

class TranslatedBlock(BaseModel):
    id: str
    text: str                                # translation (notes: the description only, without // marks)
    label: Optional[str]                     # numbering label in the target convention (usually unchanged)
    rows: Optional[list[list[str]]]          # tables: same shape as the source rows


class TranslatorOut(BaseModel):
    blocks: list[TranslatedBlock]


# ------------------------------------------------------------- proofreader

class Change(BaseModel):
    id: str
    row: Optional[int]                       # table cell, else null
    col: Optional[int]
    new_text: str
    reason: str
    category: Literal["grammar", "terminology", "name", "register", "accuracy", "omission", "punctuation", "other"]


class ProofreaderOut(BaseModel):
    changes: list[Change]


# ---------------------------------------------------------------------- QA

class QAIssue(BaseModel):
    id: Optional[str]                        # block id, or null for document-level issues
    severity: Severity
    code: str                                # number_mismatch, missing_text, added_text, name_mismatch, ...
    message: str
    suggested_fix: Optional[str]


class QAOut(BaseModel):
    issues: list[QAIssue]


# --------------------------------------------------------------- formatter

class FormatDecision(BaseModel):
    id: str
    type: Literal["heading", "paragraph", "numbered_item", "bullet", "table", "kv_table", "note",
                  "signature_block", "unreadable"]
    level: Optional[int]                     # headings: 1 title, 2 section bar, 3 sub-heading
    align: Optional[Literal["start", "center", "end", "justify"]]
    bold: Optional[bool]
    column_widths: Optional[list[float]]     # tables: relative widths
    page_break_before: bool                  # only before an apostille


class FormatterOut(BaseModel):
    decisions: list[FormatDecision]
