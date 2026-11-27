"""The agents: Intake, Glossary, Translator, Proofreader, QA, Formatter.

Each agent function takes the AgentContext and the Document model, calls the
model through ``call_agent`` with its own prompt file and output contract, and
applies the result to the model with code (history recorded on every block it
touches). The model never edits the Document directly.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from ..llm.client import Image, LLMError
from ..model import (Block, BlockStatus, BlockType, Document, Flag, GlossaryEntry, HistoryEntry, NoteKind, PageInfo,
                     Severity, TableCell, TableRow, UnreadableReason)
from ..ocr import PageScan, crop_norm, jpeg_bytes, scan_document
from ..qa.scan import figures_added, figures_match, identifiers_match, leftover_source_script, stray_punctuation
from .base import AgentContext, call_agent
from .contracts import (FormatterOut, GlossaryOut, IntakePageOut, ProofreaderOut, QAIssue, QAOut, SourceBlockOut,
                        TranslatorOut, ZoomOut)

TEXT_TYPES = {BlockType.heading, BlockType.paragraph, BlockType.numbered_item, BlockType.bullet,
              BlockType.signature_block, BlockType.note, BlockType.unreadable}


def _chunks(items: list, n: int) -> Iterable[list]:
    for i in range(0, len(items), max(1, n)):
        yield items[i:i + n]


def units(blocks: list[Block], max_blocks: int, max_pages: int) -> Iterable[list[Block]]:
    """Split a document into translation units, in order.

    A unit closes when it reaches ``max_blocks`` blocks or would span more than ``max_pages``
    source pages, whichever comes first. A long document (e.g. 300 pages) is therefore
    translated unit by unit, each with the shared glossary and the end of the previous unit
    as context, and every unit writes back into the same document model, so the Builder
    produces one Word file and one PDF for the whole document.
    """
    cur: list[Block] = []
    first_page = None
    for b in blocks:
        page = b.source_page or first_page or 1
        if cur and (len(cur) >= max_blocks or
                    (first_page is not None and page - first_page + 1 > max(1, max_pages))):
            yield cur
            cur, first_page = [], None
        if first_page is None:
            first_page = page
        cur.append(b)
    if cur:
        yield cur


def translatable(doc: Document) -> list[Block]:
    return [b for b in doc.blocks if b.type != BlockType.page_break and not b.multilingual_duplicate]


# ===================================================================== intake

def intake(ctx: AgentContext, src: Path, doc_id: str, title: str, source_language: str,
           target_language: str) -> Document:
    st = ctx.settings.pipeline
    packs = [ctx.pair.source.ocr_pack] if source_language != "auto" else ["eng", "ara", "fra", "deu", "spa", "rus"]
    scans = scan_document(src, packs, st.ocr_dpi)
    blocks: list[Block] = []
    pages: list[PageInfo] = []
    langs: Counter = Counter()
    prev_tail = ""
    for scan in scans:
        out = _intake_page(ctx, scan, len(scans), prev_tail)
        langs.update(out.languages)
        pages.append(PageInfo(number=scan.number, languages=out.languages, rotation=out.rotation_needed,
                              orientation="landscape" if scan.image.width > scan.image.height else "portrait",
                              has_stamp=out.has_stamp, has_signature=out.has_signature,
                              has_handwriting=out.has_handwriting, has_table=out.has_table,
                              ocr_confidence=round(scan.mean_conf, 1) if scan.mean_conf is not None else None))
        page_blocks = [_to_block(sb, f"p{scan.number}b{i + 1:02d}", scan.number) for i, sb in enumerate(out.blocks)]
        _zoom_uncertain(ctx, scan, out, page_blocks)
        for sb, b in zip(out.blocks, page_blocks):
            if sb.continues_previous_page and blocks and blocks[-1].type == b.type == BlockType.paragraph:
                prev = blocks[-1]
                prev.source_text = (prev.source_text.rstrip() + " " + b.source_text.lstrip()).strip()
                prev.history.append(HistoryEntry(actor="intake", field="source_text",
                                                 reason=f"joined with continuation on page {scan.number}"))
                continue
            blocks.append(b)
        if blocks:
            prev_tail = blocks[-1].source_text[-300:]
    src_lang = source_language
    if source_language == "auto":
        src_lang = langs.most_common(1)[0][0] if langs else "en"
    return Document(id=doc_id, title=title, source_language=src_lang, target_language=target_language,
                    pages=pages, blocks=blocks)


def _intake_page(ctx: AgentContext, scan: PageScan, total: int, prev_tail: str) -> IntakePageOut:
    low = [l.text for l in scan.low_conf_lines(ctx.settings.pipeline.zoom_conf_threshold)][:40]
    payload = {"page": scan.number, "pages_total": total, "ocr_draft": scan.draft_text(),
               "ocr_mean_confidence": round(scan.mean_conf, 1) if scan.mean_conf is not None else None,
               "ocr_low_confidence_lines": low, "previous_page_ends_with": prev_tail}
    res = call_agent(ctx, "intake", IntakePageOut, payload, images=[Image(jpeg_bytes(scan.image))],
                     instruction=f"Transcribe page {scan.number} of {total} into blocks.")
    return res.data


def _to_block(sb: SourceBlockOut, bid: str, page: int) -> Block:
    t = BlockType(sb.type)
    rows: list[TableRow] = []
    if t in (BlockType.table, BlockType.kv_table):
        raw = [r for r in (sb.rows or []) if r]
        if t == BlockType.kv_table and any(len(r) % 2 for r in raw):
            t = BlockType.table  # not label/value pairs after all
        rows = [TableRow(header=(sb.header_row and i == 0), cells=[TableCell(source_text=c) for c in r])
                for i, r in enumerate(raw)]
        if not rows:
            t, rows = BlockType.paragraph, []
    flags = []
    if sb.confidence < 0.8:
        flags.append(Flag(code="low_confidence", severity=Severity.major, agent="intake",
                          message=f"reading confidence {sb.confidence:.2f}"))
    text = sb.note_description if t == BlockType.note and sb.note_description else sb.text
    b = Block(id=bid, type=t, source_page=page, source_text=text or "", rows=rows,
              level=min(max(sb.level or 1, 1), 3), label=sb.label,
              note_kind=NoteKind(sb.note_kind) if sb.note_kind and t == BlockType.note else None,
              note_scope="document_end" if (t == BlockType.note and sb.repeated_on_every_page) else "inline",
              unreadable_reason=UnreadableReason(sb.unreadable_reason) if t == BlockType.unreadable else None,
              confidence=max(0.0, min(1.0, sb.confidence)), multilingual_duplicate=sb.multilingual_duplicate,
              flags=flags, status=BlockStatus.draft)
    b.bbox = _bbox(sb.bbox)
    if t == BlockType.unreadable and b.unreadable_reason is None:
        b.unreadable_reason = UnreadableReason.illegible
    if t == BlockType.unreadable and b.unreadable_reason == UnreadableReason.covered_by_stamp:
        b.flags.append(Flag(code="covered_by_stamp", severity=Severity.minor, agent="intake",
                            message="text hidden under a stamp"))
    return b



def _bbox(raw: Optional[list[int]]) -> Optional[list[float]]:
    """A usable box on the 0-1000 grid, or None (missing, wrong length, empty or out of range)."""
    if not raw or len(raw) != 4:
        return None
    x0, y0, x1, y1 = (max(0.0, min(1000.0, float(v))) for v in raw)
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None

def _zoom_uncertain(ctx: AgentContext, scan: PageScan, out: IntakePageOut, blocks: list[Block]) -> None:
    for reg in out.uncertain_regions[:12]:
        if not (0 <= reg.block_index < len(blocks)) or len(reg.bbox) != 4:
            continue
        b = blocks[reg.block_index]
        crop = crop_norm(scan.image, reg.bbox)
        try:
            z = call_agent(ctx, "intake_zoom", ZoomOut, {"block_type": b.type.value, "current_reading": b.source_text,
                                                         "why_uncertain": reg.reason},
                           images=[Image(jpeg_bytes(crop, max_side=1600))],
                           instruction="Re-read the text in this crop.").data
        except LLMError:
            continue
        if b.type in TEXT_TYPES and b.type != BlockType.note and z.text.strip() and z.confidence > b.confidence:
            b.history.append(HistoryEntry(actor="intake_zoom", field="source_text", old=b.source_text, new=z.text,
                                          reason="re-read at higher resolution"))
            b.source_text, b.confidence = z.text, z.confidence
            b.flags = [f for f in b.flags if f.code != "low_confidence"]
        if z.covered_by_stamp:
            b.flags.append(Flag(code="covered_by_stamp", severity=Severity.minor, agent="intake_zoom",
                                message="part of this text is covered by a stamp"))
        if not z.legible:
            b.flags.append(Flag(code="illegible", severity=Severity.major, agent="intake_zoom",
                                message="part of this text could not be read"))


# =================================================================== glossary

def glossary(ctx: AgentContext, docs: list[Document]) -> list[GlossaryEntry]:
    texts = []
    for d in docs:
        for b in translatable(d):
            texts.append(b.source_text)
            texts += [c.source_text for r in b.rows for c in r.cells]
    corpus = "\n".join(t for t in texts if t.strip())[:200_000]
    res = call_agent(ctx, "glossary", GlossaryOut, {"documents": [d.title for d in docs], "text": corpus},
                     instruction="Extract the batch glossary.")
    known = {g.source for g in ctx.glossary}
    out = list(ctx.glossary)
    for it in res.data.items:
        if it.source not in known:
            out.append(GlossaryEntry(source=it.source, target=it.target, kind=it.kind, confirmed=False))
    return out


# ================================================================= translator

def _src_payload(b: Block) -> dict:
    d = {"id": b.id, "type": b.type.value, "text": b.source_text}
    if b.rows:
        d["rows"] = [[c.source_text for c in r.cells] for r in b.rows]
    if b.label:
        d["label"] = b.label
    if b.type == BlockType.note:
        d["note_kind"] = b.note_kind.value if b.note_kind else None
    return d


def translate(ctx: AgentContext, doc: Document, only: set[str] | None = None,
              fix_requests: dict[str, list[str]] | None = None) -> Document:
    st = ctx.settings.pipeline
    todo = [b for b in translatable(doc) if only is None or b.id in only]
    order = [b.id for b in translatable(doc)]
    by_id = {b.id: b for b in doc.blocks}
    for chunk in units(todo, st.chunk_blocks, st.chunk_max_pages):
        first = order.index(chunk[0].id)
        ctx_blocks = [by_id[i] for i in order[max(0, first - st.context_overlap_blocks):first]]
        payload = {"translate": [_src_payload(b) for b in chunk],
                   "context_before": [{"source": b.source_text, "translation": b.translated_text}
                                      for b in ctx_blocks if b.translated_text]}
        if fix_requests:
            payload["fix_requests"] = [{"id": b.id, "problems": fix_requests[b.id]} for b in chunk
                                       if b.id in fix_requests]
        res = call_agent(ctx, "translator", TranslatorOut, payload,
                         instruction=f"Translate these {len(chunk)} blocks.")
        got = {t.id: t for t in res.data.blocks}
        missing = [b for b in chunk if b.id not in got]
        if missing:  # one targeted retry for blocks the model skipped
            res2 = call_agent(ctx, "translator", TranslatorOut, {"translate": [_src_payload(b) for b in missing]},
                              instruction=f"Translate these {len(missing)} blocks.")
            got.update({t.id: t for t in res2.data.blocks})
        for b in chunk:
            t = got.get(b.id)
            if t is None:
                b.flags.append(Flag(code="not_translated", severity=Severity.blocker, agent="translator",
                                    message="the translator returned no text for this block"))
                continue
            _apply_translation(b, t, "translator", "fix" if fix_requests else "translation")
    return doc


def _apply_translation(b: Block, t, actor: str, reason: str) -> None:
    if b.rows:
        rows = t.rows or []
        shape_ok = len(rows) == len(b.rows) and all(len(rows[i]) == len(r.cells) for i, r in enumerate(b.rows))
        if not shape_ok:
            b.flags.append(Flag(code="table_shape", severity=Severity.blocker, agent=actor,
                                message="translated table does not match the source table's rows and cells"))
        for i, r in enumerate(b.rows):
            for j, c in enumerate(r.cells):
                new = rows[i][j] if i < len(rows) and j < len(rows[i]) else c.translated_text
                if new != c.translated_text:
                    b.history.append(HistoryEntry(actor=actor, field=f"rows[{i}][{j}]", old=c.translated_text or None,
                                                  new=new, reason=reason))
                    c.translated_text = new
    else:
        if t.text != b.translated_text:
            b.history.append(HistoryEntry(actor=actor, old=b.translated_text or None, new=t.text, reason=reason))
            b.translated_text = t.text
    if t.label and t.label != b.label:
        b.label = t.label
    b.runs = None  # the Builder segments the new text
    b.status = BlockStatus.translated
    b.flags = [f for f in b.flags if not (f.agent == "translator" and f.code == "not_translated")]



def _reviewer(instruction: str) -> str:
    """A reviewer's instruction for a re-run, passed in the user message (the system prompt stays cached)."""
    return f"\nReviewer instruction: {instruction.strip()}" if instruction and instruction.strip() else ""

# ================================================================ proofreader

def _pair_payload(b: Block) -> dict:
    d = {"id": b.id, "type": b.type.value, "source": b.source_text, "translation": b.translated_text}
    if b.rows:
        d["source_rows"] = [[c.source_text for c in r.cells] for r in b.rows]
        d["translated_rows"] = [[c.translated_text for c in r.cells] for r in b.rows]
    return d


def proofread(ctx: AgentContext, doc: Document, only: set[str] | None = None,
              instruction: str = "") -> list[dict]:
    st = ctx.settings.pipeline
    by_id = {b.id: b for b in doc.blocks}
    todo = [b for b in translatable(doc) if only is None or b.id in only]
    applied = []
    for chunk in units(todo, st.chunk_blocks, st.chunk_max_pages):
        res = call_agent(ctx, "proofreader", ProofreaderOut, {"blocks": [_pair_payload(b) for b in chunk]},
                         instruction=f"Proofread these {len(chunk)} blocks." + _reviewer(instruction))
        for ch in res.data.changes:
            b = by_id.get(ch.id)
            if b is None:
                continue
            if ch.row is not None and ch.col is not None and b.rows:
                if ch.row < len(b.rows) and ch.col < len(b.rows[ch.row].cells):
                    c = b.rows[ch.row].cells[ch.col]
                    b.history.append(HistoryEntry(actor="proofreader", field=f"rows[{ch.row}][{ch.col}]",
                                                  old=c.translated_text, new=ch.new_text,
                                                  reason=f"{ch.category}: {ch.reason}"))
                    c.translated_text = ch.new_text
            elif not b.rows:
                b.history.append(HistoryEntry(actor="proofreader", old=b.translated_text, new=ch.new_text,
                                              reason=f"{ch.category}: {ch.reason}"))
                b.translated_text = ch.new_text
                b.runs = None
            else:
                continue
            applied.append(ch.model_dump())
        for b in chunk:
            b.status = BlockStatus.proofread
    return applied


# ========================================================================= QA

def deterministic_qa(ctx: AgentContext, doc: Document, only: set[str] | None = None) -> list[QAIssue]:
    issues: list[QAIssue] = []
    keep = lambda bid: only is None or bid in only  # noqa: E731
    for b in translatable(doc):
        if not keep(b.id):
            continue
        empty = (not b.rows and b.source_text.strip() and not b.translated_text.strip()) or \
                (b.rows and any(c.source_text.strip() and not c.translated_text.strip() for r in b.rows for c in r.cells))
        if empty and b.type != BlockType.unreadable:
            issues.append(QAIssue(id=b.id, severity="blocker", code="missing_translation",
                                  message="source text has no translation", suggested_fix=None))
    for f in figures_match(doc):
        if keep(f.block_id):
            issues.append(QAIssue(id=f.block_id, severity="blocker", code="number_mismatch",
                                  message=f"figures in the source not found in the translation: {f.detail}",
                                  suggested_fix=None))
    for f in figures_added(doc) + identifiers_match(doc):
        if keep(f.block_id):
            issues.append(QAIssue(id=f.block_id, severity="blocker", code=f.code,
                                  message=("figures in the translation that are not in the source: " if f.code == "figure_added"
                                           else "identifiers not kept exactly as written: ") + f.detail,
                                  suggested_fix=None))
    for f in leftover_source_script(doc):
        if keep(f.block_id):
            issues.append(QAIssue(id=f.block_id, severity="major",
                                  code="leftover_source_script", message=f"source-script text left: {f.detail}",
                                  suggested_fix=None))
    for f in stray_punctuation(doc):
        if keep(f.block_id):
            issues.append(QAIssue(id=f.block_id, severity="minor", code=f.code, message=f.detail, suggested_fix=None))
    return issues


def qa(ctx: AgentContext, doc: Document, only: set[str] | None = None, instruction: str = "") -> list[QAIssue]:
    st = ctx.settings.pipeline
    auto = deterministic_qa(ctx, doc, only)
    todo = [b for b in translatable(doc) if only is None or b.id in only]
    model_issues: list[QAIssue] = []
    for chunk in units(todo, st.chunk_blocks, st.chunk_max_pages):
        ids = {b.id for b in chunk}
        res = call_agent(ctx, "qa", QAOut, {"blocks": [_pair_payload(b) for b in chunk],
                                            "automated_findings": [i.model_dump() for i in auto if i.id in ids]},
                         instruction=f"Check these {len(chunk)} blocks." + _reviewer(instruction))
        model_issues += res.data.issues
    issues = auto + model_issues
    auto_ids = {id(i) for i in auto}
    by_id = {b.id: b for b in doc.blocks}
    for b in todo:  # replace earlier open QA flags on the checked blocks (a reviewer's resolution stays on record)
        b.flags = [f for f in b.flags if f.agent not in ("qa", "qa_auto") or f.resolved]
    for i in issues:
        if i.id in by_id:
            by_id[i.id].flags.append(Flag(code=i.code, severity=Severity(i.severity), message=i.message,
                                          agent="qa_auto" if id(i) in auto_ids else "qa"))
    for b in todo:
        if not any(f.severity == Severity.blocker and not f.resolved for f in b.flags):
            b.status = BlockStatus.qa_passed
    return issues


# ================================================================== formatter

def format_document(ctx: AgentContext, doc: Document) -> Document:
    # deterministic: identical stamp/signature descriptions on several pages are described once at the end
    seen: dict[str, set] = {}
    for b in doc.blocks:
        if b.type == BlockType.note:
            seen.setdefault(b.translated_text.strip(), set()).add(b.source_page)
    for b in doc.blocks:
        if b.type == BlockType.note and len(seen.get(b.translated_text.strip(), ())) > 1:
            b.note_scope = "document_end"

    items = translatable(doc)
    payload = {"blocks": [{"id": b.id, "type": b.type.value, "level": b.level if b.type == BlockType.heading else None,
                           "source_page": b.source_page, "excerpt": (b.translated_text or b.source_text)[:160],
                           "columns": max((len(r.cells) for r in b.rows), default=0)} for b in items]}
    decisions = {}
    for chunk in _chunks(payload["blocks"], 120):
        res = call_agent(ctx, "formatter", FormatterOut, {"blocks": chunk},
                         instruction=f"Decide the layout for these {len(chunk)} blocks.")
        decisions.update({d.id: d for d in res.data.decisions})
    out: list[Block] = []
    for b in doc.blocks:
        d = decisions.get(b.id)
        if d is not None:
            if d.page_break_before:
                out.append(Block(id=f"{b.id}_pb", type=BlockType.page_break, source_page=b.source_page))
            new_t = BlockType(d.type)
            text_like = {BlockType.heading, BlockType.paragraph, BlockType.signature_block, BlockType.bullet,
                         BlockType.numbered_item}
            if new_t != b.type:
                if b.type in text_like and new_t in text_like:
                    b.type = new_t
                elif {b.type, new_t} == {BlockType.table, BlockType.kv_table} and b.rows and \
                        (new_t == BlockType.table or all(len(r.cells) % 2 == 0 for r in b.rows)):
                    b.type = new_t
            if b.type == BlockType.heading and d.level:
                b.level = min(max(d.level, 1), 3)
            if d.align:
                b.layout.align = d.align
            if d.bold is not None and b.type not in (BlockType.heading,):
                b.layout.bold = d.bold
            if d.column_widths and b.rows:
                ncols = max(sum(c.colspan for c in r.cells) for r in b.rows)
                if len(d.column_widths) == ncols and all(w > 0 for w in d.column_widths):
                    b.column_widths = d.column_widths
        out.append(b)
    doc.blocks = out
    return doc
